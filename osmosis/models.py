import json

from django.db import models
from django.db import connections
from django.db import transaction
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
        @transaction.atomic
        def _wrapped(*args, **kwargs):
            return func(*args, **kwargs)

        return _wrapped

class ImportTask(models.Model):
    source_data = models.FileField("File", upload_to="/") #FIXME: We should make upload_to somehow configurable

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

        if not self.row_columns:
            #On first iteration, the line will be the column headings, store those
            #and return False to skip processing
            self.row_columns = line.split(",") ##FIXME: Use CSV module
            return False

        cols = line.split(",")
        return { x: cols[i] for i, x in enumerate(self.row_columns) }

    def process(self):
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
            if data_length == meta.rows_per_shard or not data:
                #If we hit the predefined shard count, or the EOF of the file then process what we have

                new_shard = ImportShard.objects.create(
                    task=self,
                    source_data_json=json.dumps(shard_data),
                    last_row_processed=0,
                    total_rows=data_length,
                    start_line_number=lineno - data_length
                )

                deferred.defer(new_shard.process)

            if not data:
                #Break at the end of the file
                break

    def preprocess_form(self, form, data):
        return form

    def import_row(self, forms, cleaned_data):
        """
            Called when a row of source data is found to be valid and is ready for saving
        """
        raise NotImplementedError()

    def handle_error(self, lineno, errors):
        raise NotImplementedError()

class ModelImportTask(ImportTask):
    def import_row(self, forms, cleaned_data):
        return [ form.save() for form in forms ]

class ImportShard(models.Model):
    task = models.ForeignKey(ImportTask)
    source_data_json = models.TextField()
    last_row_processed = models.PositiveIntegerField()
    total_rows = models.PositiveIntegerField()
    start_line_number = models.PositiveIntegerField()

    def process(self):
        meta = self.task.get_meta()

        this = ImportShard.objects.get(pk=self.pk)  #Reload, self is pickled

        source_data = json.loads(this.source_data_json)
        for i in xrange(this.last_row_processed, this.total_rows):  #Always continue from the last processed row
            data = source_data[i]

            forms = [ self.task.preprocess_form(form(data), data) for form in meta.forms ]

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
                    errors.extend(form.errors)

                self.task.handle_error(this.start_line_number + i, errors)

            #Now update the last processed row, transactionally
            @transactional
            def update_shard():
                pass

            update_shard()
