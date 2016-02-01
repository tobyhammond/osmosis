import json
import unicodecsv as csv
import StringIO

from django.apps import apps
from django.db import models
from django.db import connections
from django.db import transaction
from django.db.models.loading import get_model

from django.core.exceptions import ValidationError
from django.utils.importlib import import_module

from google.appengine.ext import deferred
from google.appengine.ext import db

from google.appengine.api.app_identity import get_default_gcs_bucket_name
from google.appengine.ext.blobstore import BlobInfo, create_gs_key

import cloudstorage

try:
    from djangae.storage import BlobstoreFile, BlobstoreStorage
except ImportError:
    from djangoappengine.storage import BlobstoreFile, BlobstoreStorage


def transactional(func):
    if "djangoappengine" in unicode(connections['default']) or \
        "djangae" in unicode(connections['default']):

        @db.transactional(xg=True)
        def _wrapped(*args, **kwargs):
            return func(*args, **kwargs)

        return _wrapped
    else:
        @transaction.commit_on_success
        def _wrapped(*args, **kwargs):
            return func(*args, **kwargs)

        return _wrapped


class ImportStatus(object):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"

    @classmethod
    def choices(cls):
        return (ImportStatus.PENDING, "Pending"), (ImportStatus.IN_PROGRESS, "In Progress"), (ImportStatus.FINISHED, "Finished")


class AbstractImportTask(models.Model):
    model_path = models.CharField(max_length=500, editable=False)

    source_data = models.FileField("File", upload_to="/", max_length=1023)

    error_csv = models.FileField("Error File", upload_to="/", editable=False, null=True, max_length=1023)
    error_csv_filename = models.CharField(max_length=1023, editable=False)

    row_count = models.PositiveIntegerField(default=0, editable=False)
    shard_count = models.PositiveIntegerField(default=0, editable=False)
    shards_processed = models.PositiveIntegerField(default=0, editable=False)
    # This field is here because we don't have foreign key relation anymore and
    # retrieving this from ImportShard wasn't possible due to transaction
    shards_error_csv_written = models.BooleanField(default=False, editable=False)

    status = models.CharField(max_length=32, choices=ImportStatus.choices(), default=ImportStatus.PENDING, editable=False)

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super(AbstractImportTask, self).__init__(*args, **kwargs)
        if not self.model_path:
            self.model_path = ".".join([self._meta.app_label, self.__class__.__name__])

    class Osmosis:
        forms = []
        rows_per_shard = 100
        generate_error_csv = True
        queue = deferred.deferred._DEFAULT_QUEUE
        error_csv_subdirectory = "osmosis-errors"
        shard_model = "osmosis.ImportShard"

    @classmethod
    def required_fields(cls):
        """
        Get a list of the required form fields from all of the
        forms in cls.Osmosis.
        """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                if field.required and field.initial is None:
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def optional_fields(cls):
        """
        Get a list of the optional form fields from all of the forms in cls.Osmosis.
        """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                if not field.required or (field.required and field.initial is not None):
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def all_fields(cls):
        """
        Get an aggregate list of the form fields from all of the forms in cls.Osmosis.
        """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                fields.append((name, field.help_text))
        return fields

    @classmethod
    def get_meta(cls):
        """
        Get the info from self.Osmosis (where self can be a subclass),
        using defaults from the parent ImportTask.Osmosis for values
        which are not defined on SubClass.Osmosis.
        """
        meta = getattr(cls, "Osmosis")

        if not hasattr(meta, "_initialised"):

            for attr in (x for x in dir(AbstractImportTask.Osmosis) if not x.startswith("_")):
                if not hasattr(meta, attr):
                    setattr(meta, attr, getattr(AbstractImportTask.Osmosis, attr))

            # If we were given any forms by their module path, then swap
            # them here so that meta.forms is always a list of classes
            new_forms = []
            for form in meta.forms:
                if isinstance(form, basestring):
                    module, klass = form.rsplit(".", 1)
                    new_forms.append(getattr(import_module(module), klass))
                else:
                    new_forms.append(form)
            meta.forms = new_forms

            meta._initialised = True

        return meta

    @classmethod
    def get_shard_model(cls):
        shard_model = cls.get_meta().shard_model.split('.')
        return apps.get_model(app_label=shard_model[0], model_name=shard_model[1])

    def defer(self, kallable, *args, **kwargs):
        kwargs['_queue'] = self.get_meta().queue
        deferred.defer(kallable, *args, **kwargs)

    def start(self):
        self.save()  # Make sure we are saved before processing

        self.row_columns = None
        self.defer(self.process)

    def next_source_row(self, handle):
        """
        Given a file handle, return the next row of data as a key value dict.

        Return None to denote the EOF
        Return False to skip this row of data entirely
        """

        if not getattr(self, "detected_dialect", None):
            # Sniff for the dialect of the CSV file

            pos = handle.tell()
            handle.seek(0)
            readahead = handle.read(1024)
            handle.seek(pos)

            try:
                dialect = csv.Sniffer().sniff(readahead, ",")
            except csv.Error:
                # Fallback to excel format
                dialect = csv.excel

            dialect_attrs = [
                "delimiter",
                "doublequote",
                "escapechar",
                "lineterminator",
                "quotechar",
                "quoting",
                "skipinitialspace"
            ]

            self.detected_dialect = {x: getattr(dialect, x) for x in dialect_attrs}

        if not getattr(self, "reader", None):
            self.reader = csv.reader(handle, **self.detected_dialect)

        if not getattr(self, "detected_columns", None):
            # On first iteration, the line will be the column headings,
            # store those and return False to skip processing
            columns = self.reader.next()
            self.detected_columns = columns
            return False

        cols = self.detected_columns

        try:
            values = self.reader.next()
        except StopIteration:
            return None

        if not values:
            return None

        return dict(zip(cols, values))

    def process(self):
        # Reload, we've been pickled in'it
        self = self.__class__.objects.get(pk=self.pk)
        self.status = ImportStatus.IN_PROGRESS

        meta = self.get_meta()

        uploaded_file = self.source_data
        shard_data = []
        lineno = 0

        while True:
            lineno += 1  # Line numbers are 1-based
            data = self.next_source_row(uploaded_file)

            if data is False:
                # Skip this row
                continue
            elif data:
                shard_data.append(data)  # Keep a buffer of the data to process in this shard

            data_length = len(shard_data)
            if shard_data and (data_length == meta.rows_per_shard or data is None):
                # If we hit the predefined shard count, or the EOF of the
                # file then process what we have

                new_shard = self.get_shard_model().objects.create(
                    task_id=self.pk,
                    task_model_path=self.model_path,
                    source_data_json=json.dumps(shard_data),
                    last_row_processed=0,
                    total_rows=data_length,
                    start_line_number=lineno - data_length
                )

                self.shard_count += 1
                self.save()

                self.defer(new_shard.process)
                shard_data = []

            if not data:
                # Break at the end of the file
                break

        # 2 == HEADER + 1-based to 0-based
        self.__class__.objects.filter(pk=self.pk).update(row_count=lineno - 2)

    def instantiate_form(self, form_class, data):
        return form_class(data)

    def import_row(self, forms, cleaned_data):
        """
        Called when a row of source data is found to be valid and is ready for saving
        """
        raise NotImplementedError()

    def _error_csv_filename(self):
        meta = self.get_meta()
        return '/%s/%s/%s.csv' % (
            get_default_gcs_bucket_name(),
            meta.error_csv_subdirectory,
            self.pk
        )

    def finish(self):
        """
        Called when all shards have finished processing
        """

        # If this was called before, don't do anything
        if self.status == ImportStatus.FINISHED:
            return

        if self.get_meta().generate_error_csv:
            self.error_csv_filename = self._error_csv_filename()

            with cloudstorage.open(self.error_csv_filename, 'w') as f:
                # Concat all error csvs from shards into 1 file
                has_written = False

                shards = self.get_shard_model().objects.filter(task_id=self.pk, task_model_path=self.model_path)

                # The shards haven't necessarily finished writing their error files when this is called,
                # because that happens in a defer. So we redefer this until they're all done.
                if [shard for shard in shards if not shard.error_csv_written]:
                    self.defer(self.finish)
                    return

                for shard in shards:
                    if not shard.error_csv_filename:
                        continue

                    # If this is the first row, write the column headers
                    if not has_written:
                        data = json.loads(shard.source_data_json)[0]
                        cols = getattr(self, "detected_columns", data.keys()) + [ "errors" ]
                        csvwriter = csv.writer(f)
                        csvwriter.writerow(cols)
                        has_written = True

                    # Write the shard's error file into the master file
                    f.write(cloudstorage.open(shard.error_csv_filename).read())
                    cloudstorage.delete(shard.error_csv_filename)

            if has_written:
                # Create a blobstore key for the GCS file
                blob_key = create_gs_key('/gs%s' % self.error_csv_filename)
                self.error_csv = '%s/errors.csv' % blob_key
            else:
                cloudstorage.delete(self.error_csv_filename)

        self.status = ImportStatus.FINISHED
        self.save()

    def save(self, *args, **kwargs):
        defer_finish = False

        if all([
            self.status == ImportStatus.IN_PROGRESS,
            self.shard_count,
            self.shards_processed == self.shard_count,
            not self.shards_error_csv_written,
        ]):
            # Defer the finish callback when we've processed all shards
            defer_finish = True

        result = super(AbstractImportTask, self).save(*args, **kwargs)

        if defer_finish:
            self.defer(self.finish)
        return result

    def handle_error(self, lineno, data, errors):
        pass


class ImportTask(AbstractImportTask):
    """
    Concrete implementation of AbstractImportTask
    It exists for compatibility purposes, you should not use it for new projects
    """
    pass


class ModelImportTaskMixin(object):
    def import_row(self, forms, cleaned_data):
        return [form.save() for form in forms]


class ImportShard(models.Model):
    task_model_path = models.CharField(max_length=500, editable=False)
    task_id = models.PositiveIntegerField()

    source_data_json = models.TextField()
    last_row_processed = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(default=0)
    start_line_number = models.PositiveIntegerField(default=0)
    complete = models.BooleanField(default=False)
    error_csv_filename = models.CharField(max_length=1023)
    error_csv_written = models.BooleanField(default=False)

    def __init__(self, *args, **kwargs):
        self.errors = []
        super(ImportShard, self).__init__(*args, **kwargs)

    @property
    def task(self):
        model = get_model(*self.task_model_path.split("."))
        return model.objects.get(pk=self.task_id)

    def process(self):
        imported_rows = []
        meta = self.task.get_meta()
        task_model = get_model(*self.task.model_path.split("."))

        this = self.__class__.objects.get(pk=self.pk)  # Reload, self is pickled
        source_data = json.loads(this.source_data_json)

        # If there are no rows to process
        mark_shard_complete = this.last_row_processed == this.total_rows - 1 or this.total_rows == 0

        for i in xrange(this.last_row_processed, this.total_rows):  # Always continue from the last processed row
            data = source_data[i]

            forms = [self.task.instantiate_form(form, data) for form in meta.forms]

            if all([form.is_valid() for form in forms]):
                # All forms are valid, let's process this shizzle

                cleaned_data = {}
                for form in forms:
                    cleaned_data.update(form.cleaned_data)

                try:
                    imported_rows.append(self.task.import_row(forms, cleaned_data))
                except ValidationError, e:
                    # We allow subclasses to raise a validation error on import_row
                    errors = []
                    if hasattr(e, 'message_dict'):
                        for name, errs in e.message_dict.items():
                            for err in errs:
                                errors.append("{0}: {1}".format(name, err))
                    else:
                        # Pre 1.6, ValidationError does not necessarily have a message_dict
                        for err in e.messages:
                            errors.append(err)

                    self.handle_error(this.start_line_number + i, cleaned_data, errors)
            else:
                # We've encountered an error, call the error handler
                errors = []
                for form in forms:
                    for name, errs in form.errors.items():
                        for err in errs:
                            errors.append("{0}: {1}".format(name, err))

                self.handle_error(this.start_line_number + i, data, errors)

            # Now update the last processed row, transactionally
            @transactional
            def update_shard(_this):
                _this = _this.__class__.objects.get(pk=_this.pk)
                _this.last_row_processed += 1
                _this.save()
                return _this

            this = update_shard(this)
            # If this was the last iteration then mark as complete
            mark_shard_complete = i == this.total_rows - 1

        if mark_shard_complete:
            self.finish(imported_rows)
            deferred.defer(this._finalize_errors, _queue=self.task.get_meta().queue)

    @transactional
    def finish(self, imported_rows=None):
        self = self.__class__.objects.get(pk=self.pk)
        if self.complete:
            return

        task_model = get_model(*self.task.model_path.split("."))
        task = task_model.objects.get(pk=self.task_id)
        task.shards_processed += 1
        task.save()

        self.complete = True
        self.save()

    def handle_error(self, lineno, data, errors):
        self.task.handle_error(lineno, data, errors)
        self._write_error_row(data, errors)

    def _write_error_row(self, data, errors):
        if not get_model(*self.task.model_path.split(".")).get_meta().generate_error_csv:
            return

        ImportShardError.objects.create(
            shard=self,
            line=json.dumps(data.values() + [". ".join(errors)])
        )

    def _error_csv_filename(self):
        meta = self.task.get_meta()
        return "/%s/%s/%s-shard-%s.csv" % (
            get_default_gcs_bucket_name(),
            meta.error_csv_subdirectory,
            self.task.pk,
            self.pk
        )

    def _get_errors(self):
        return self.importsharderror_set.all()

    def _finalize_errors(self):
        self = self.__class__.objects.get(pk=self.pk)
        task_model = get_model(*self.task.model_path.split("."))
        task = task_model.objects.get(pk=self.task_id)

        if not task_model.get_meta().generate_error_csv:
            self.error_csv_written = True
            task.shards_error_csv_written = True
            self.save()
            task.save()
            return

        errors = self._get_errors()
        if errors:
            self.error_csv_filename = self._error_csv_filename()

            def _write(_this):
                with cloudstorage.open(self.error_csv_filename, "w") as f:
                    writer = csv.writer(f)
                    for error in errors:
                        writer.writerow(json.loads(error.line))
            _write(self)

        self.error_csv_written = True
        task.shards_error_csv_written = True
        self.save()
        task.save()


class ImportShardError(models.Model):
    shard = models.ForeignKey(ImportShard)
    line = models.TextField()
