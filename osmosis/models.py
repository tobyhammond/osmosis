import json
import csv
import StringIO
import logging

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

        @db.transactional
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
        return ((ImportStatus.PENDING, "Pending"), (ImportStatus.IN_PROGRESS, "In Progress"), (ImportStatus.FINISHED, "Finished"))

class ImportTask(models.Model):
    model_path = models.CharField(max_length=500, editable=False)

    source_data = models.FileField("File", upload_to="/", max_length=1023) #FIXME: We should make upload_to somehow configurable

    error_csv = models.FileField("Error File", upload_to="/", editable=False, null=True, max_length=1023) #FIXME: Should make upload_to configurable
    error_csv_filename = models.CharField(max_length=1023, editable=False)

    row_count = models.PositiveIntegerField(default=0, editable=False)
    shard_count = models.PositiveIntegerField(default=0, editable=False)
    shards_processed = models.PositiveIntegerField(default=0, editable=False)

    status = models.CharField(max_length=32, choices=ImportStatus.choices(), default=ImportStatus.PENDING, editable=False)

    def __init__(self, *args, **kwargs):
        super(ImportTask, self).__init__(*args, **kwargs)
        if not self.model_path:
            self.model_path = ".".join([self._meta.app_label, self.__class__.__name__])

    class Osmosis:
        forms = []
        rows_per_shard = 100
        generate_error_csv = True
        queue = deferred.deferred._DEFAULT_QUEUE
        error_csv_subdirectory = "osmosis-errors"

    @classmethod
    def required_fields(cls):
        """ Get a list of the required form fields from all of the forms in cls.Osmosis. """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                if field.required and field.initial is None:
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def optional_fields(cls):
        """ Get a list of the optional form fields from all of the forms in cls.Osmosis. """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                if not field.required or (field.required and field.initial is not None):
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def all_fields(cls):
        """ Get an aggregate list of the form fields from all of the forms in cls.Osmosis. """
        meta = cls.get_meta()
        fields = []
        for form in meta.forms:
            for name, field in form.base_fields.items():
                fields.append((name, field.help_text))
        return fields

    @classmethod
    def get_meta(cls):
        """ Get the info from self.Osmosis (where self can be a subclass), using defaults from
            the parent ImportTask.Osmosis for values which are not defined on SubClass.Osmosis.
        """
        meta = getattr(cls, "Osmosis")

        if not hasattr(meta, "_initialised"):

            for attr in ( x for x in dir(ImportTask.Osmosis) if not x.startswith("_") ):
                if not hasattr(meta, attr):
                    setattr(meta, attr, getattr(ImportTask.Osmosis, attr))

            #If we were given any forms by their module path, then swap them here
            #so that meta.forms is always a list of classes
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

    def defer(self, kallable, *args, **kwargs):
        kwargs['_queue'] = self.get_meta().queue
        deferred.defer(kallable, *args, **kwargs)

    def start(self):
        self.save()  #Make sure we are saved before processing

        self.row_columns = None
        self.defer(self.process)

    def next_source_row(self, handle):
        """
            Given a file handle, return the next row of data as a key value dict.

            Return None to denote the EOF
            Return False to skip this row of data entirely
        """
        line = handle.readline()  #By default, assume CSV

        if not line:
            return None

        if not line.strip():
            #Skip lines with just whitespace
            return False

        if not getattr(self, "detected_dialect", None):
            #Sniff for the dialect of the CSV file

            pos = handle.tell()
            handle.seek(0)
            readahead = handle.read(1024)
            handle.seek(pos)

            try:
                dialect = csv.Sniffer().sniff(readahead, ",")
            except csv.Error:
                #Fallback to excel format
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

            self.detected_dialect = { x: getattr(dialect, x) for x in dialect_attrs }

        reader = csv.reader(StringIO.StringIO(line), **self.detected_dialect)

        if not getattr(self, "detected_columns", None):
            #On first iteration, the line will be the column headings, store those
            #and return False to skip processing
            columns = reader.next()
            self.detected_columns = columns
            return False

        cols = self.detected_columns
        values = reader.next()

        return { x: values[i] for i, x in enumerate(cols) }

    def process(self):
        #Reload, we've been pickled in'it
        self = self.__class__.objects.get(pk=self.pk)
        self.status = ImportStatus.IN_PROGRESS

        meta = self.get_meta()

        uploaded_file = self.source_data
        shard_data = []
        lineno = 0

        while True:
            lineno += 1  #Line numbers are 1-based
            data = self.next_source_row(uploaded_file)

            if data is False:
                # Skip this row
                continue
            elif data:
                shard_data.append(data)  #Keep a buffer of the data to process in this shard

            data_length = len(shard_data)
            if shard_data and (data_length == meta.rows_per_shard or data is None):
                #If we hit the predefined shard count, or the EOF of the file then process what we have

                new_shard = ImportShard.objects.create(
                    task=self,
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
                #Break at the end of the file
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
        if self.get_meta().generate_error_csv:
            self.error_csv_filename = self._error_csv_filename()

            with cloudstorage.open(self.error_csv_filename, 'w') as f:
                # Concat all error csvs from shards into 1 file
                has_written = False
                for shard in self.importshard_set.all():
                    if not shard.error_csv_filename:
                        continue

                    # If this is the first row, write the column headers
                    if not has_written:
                        data = json.loads(shard.source_data_json)[0]
                        cols = getattr(self, "detected_columns", sorted(data.keys())) + [ "errors" ]
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
                self.save()
            else:
                cloudstorage.delete(self.error_csv_filename)

    def save(self, *args, **kwargs):
        defer_finish = False
        if self.status == ImportStatus.IN_PROGRESS and self.shard_count and self.shards_processed == self.shard_count:
            #Defer the finish callback when we've processed all shards
            self.status = ImportStatus.FINISHED
            defer_finish = True

        result = super(ImportTask, self).save(*args, **kwargs)

        if defer_finish:
            self.defer(self.finish)
        return result

    def handle_error(self, lineno, data, errors):
        pass


class ModelImportTaskMixin(object):
    def import_row(self, forms, cleaned_data):
        return [ form.save() for form in forms ]


class ImportShard(models.Model):
    task = models.ForeignKey(ImportTask)

    source_data_json = models.TextField()
    last_row_processed = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(default=0)
    start_line_number = models.PositiveIntegerField(default=0)
    complete = models.BooleanField(default=False)
    error_csv_filename = models.CharField(max_length=1023)

    def __init__(self, *args, **kwargs):
        self.errors = []
        super(ImportShard, self).__init___(*args, **kwargs)

    def process(self):
        meta = self.task.get_meta()
        task_model = get_model(*self.task.model_path.split("."))

        this = ImportShard.objects.get(pk=self.pk)  #Reload, self is pickled
        source_data = json.loads(this.source_data_json)

        #If there are no rows to process
        mark_shard_complete = this.last_row_processed == this.total_rows - 1 or this.total_rows == 0

        for i in xrange(this.last_row_processed, this.total_rows):  #Always continue from the last processed row
            data = source_data[i]

            forms = [ self.task.instantiate_form(form, data) for form in meta.forms ]

            if all([ form.is_valid() for form in forms ]):
                #All forms are valid, let's process this shizzle

                cleaned_data = {}
                for form in forms:
                    cleaned_data.update(form.cleaned_data)

                try:
                    self.task.import_row(forms, cleaned_data)
                except ValidationError, e:
                    #We allow subclasses to raise a validation error on import_row
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

            #Now update the last processed row, transactionally
            @transactional
            def update_shard(_this):
                _this = ImportShard.objects.get(pk=_this.pk)
                _this.last_row_processed += 1
                _this.save()
                return _this

            this = update_shard(this)

            mark_shard_complete = i == this.total_rows - 1 #If this was the last iteration then mark as complete

        if mark_shard_complete:
            @transactional
            def update_task(_this):
                if _this.complete:
                    return

                task = task_model.objects.get(pk=_this.task_id)
                task.shards_processed += 1
                task.save()

                _this.complete = True
                _this.save()

            update_task(this)
            self._finalize_errors()

    def handle_error(self, lineno, data, errors):
        self.task.handle_error(lineno, data, errors)
        self._write_error_row(data, errors)

    def _write_error_row(self, data, errors):
        if not get_model(*self.task.model_path.split(".")).get_meta().generate_error_csv:
            return

        cols = getattr(self.task, "detected_columns", sorted(data.keys())) + [ "errors" ]
        self.errors.append(data.values() + [ ". ".join(errors) ])

    def _error_csv_filename(self):
        meta = self.task.get_meta()
        return "/%s/%s/%s-shard-%s.csv" % (
            get_default_gcs_bucket_name(),
            meta.error_csv_subdirectory,
            self.task.pk,
            self.pk
        )

    def _finalize_errors(self):
        self.error_csv_filename = self._error_csv_filename()
        self.save()

        with cloudstorage.open(self.error_csv_filename, "w") as f:
            writer = csv.writer(f)
            for error in self.errors:
                writer.writerow(error)
