import json
import csv
import StringIO

from django.db import models
from django.db import connections
from django.db import transaction
from django.db.models.loading import get_model

from django.core.exceptions import ValidationError
from django.utils.importlib import import_module

from google.appengine.ext import deferred
from google.appengine.ext import db

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
    source_data = models.FileField("File", upload_to="/") #FIXME: We should make upload_to somehow configurable
    row_count = models.PositiveIntegerField(default=0, editable=False)
    shard_count = models.PositiveIntegerField(default=0, editable=False)
    shards_processed = models.PositiveIntegerField(default=0, editable=False)

    status = models.CharField(max_length=32, choices=ImportStatus.choices(), default=ImportStatus.PENDING, editable=False)

    class Osmosis:
        forms = []
        rows_per_shard = 100

    @classmethod
    def required_fields(cls):
        meta = cls.get_meta()

        fields = []

        for form in meta.forms:
            for name, field in form.base_fields.items():
                if field.required:
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def optional_fields(cls):
        meta = cls.get_meta()

        fields = []

        for form in meta.forms:
            for name, field in form.base_fields.items():
                if not field.required:
                    fields.append((name, field.help_text))
        return fields

    @classmethod
    def all_fields(cls):
        meta = cls.get_meta()

        fields = []

        for form in meta.forms:
            for name, field in form.base_fields.items():
                fields.append((name, field.help_text))
        return fields

    @classmethod
    def get_meta(cls):
        meta = getattr(cls, "Osmosis")

        for attr in ( x for x in dir(ImportTask.Osmosis) if not x.startswith("_") ):
            if not hasattr(meta, attr):
                setattr(meta, attr, getattr(ImportTask.Osmosis, attr))

        #If we were given any forms by their module path, then swap them here
        #so that get_meta().forms is always a list of classes
        new_forms = []
        for form in meta.forms:
            if isinstance(form, basestring):
                module, klass = form.rsplit(".", 1)
                new_forms.append(getattr(import_module(module), klass))
            else:
                new_forms.append(form)

        meta.forms = new_forms
        return meta

    def start(self):
        self.save()  #Make sure we are saved before processing

        self.row_columns = None
        deferred.defer(self.process)

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
                    task_model_path=".".join([self._meta.app_label, self.__class__.__name__]),
                    source_data_json=json.dumps(shard_data),
                    last_row_processed=0,
                    total_rows=data_length,
                    start_line_number=lineno - data_length
                )

                self.shard_count += 1
                self.save()

                deferred.defer(new_shard.process)
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

    def handle_error(self, lineno, data, errors):
        raise NotImplementedError()

    def finish(self):
        """
            Called when all shards have finished processing
        """
        pass

    def save(self, *args, **kwargs):
        defer_finish = False
        if self.status == ImportStatus.IN_PROGRESS and self.shard_count and self.shards_processed == self.shard_count:
            #Defer the finish callback when we've processed all shards
            self.status = ImportStatus.FINISHED
            defer_finish = True

        result = super(ImportTask, self).save(*args, **kwargs)

        if defer_finish:
            deferred.defer(self.finish)
        return result

class ModelImportTaskMixin(object):
    def import_row(self, forms, cleaned_data):
        return [ form.save() for form in forms ]

class ImportShard(models.Model):
    task = models.ForeignKey(ImportTask)
    task_model_path = models.CharField(max_length=500)

    source_data_json = models.TextField()
    last_row_processed = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(default=0)
    start_line_number = models.PositiveIntegerField(default=0)
    complete = models.BooleanField()

    def process(self):
        meta = self.task.get_meta()
        task_model = get_model(*self.task_model_path.split("."))

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
                    self.task.handle_error(this.start_line_number + i, e.messages)
            else:
                # We've encountered an error, call the error handler
                errors = []
                for form in forms:
                    for name, errs in form._get_errors().items():
                        for err in errs:
                            errors.append("{0}: {1}".format(name, err))

                self.task.handle_error(this.start_line_number + i, data, errors)

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
