# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Deleting field 'ImportShard.task'
        db.delete_column(u'osmosis_importshard', 'task_id')


    def backwards(self, orm):

        # User chose to not deal with backwards NULL issues for 'ImportShard.task'
        raise RuntimeError("Cannot reverse this migration. 'ImportShard.task' and its values cannot be restored.")
        
        # The following code is provided here to aid in writing a correct migration        # Adding field 'ImportShard.task'
        db.add_column(u'osmosis_importshard', 'task',
                      self.gf('django.db.models.fields.related.ForeignKey')(to=orm['osmosis.ImportTask']),
                      keep_default=False)


    models = {
        u'osmosis.importshard': {
            'Meta': {'object_name': 'ImportShard'},
            'complete': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'error_csv_filename': ('django.db.models.fields.CharField', [], {'max_length': '1023'}),
            'error_csv_written': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'last_row_processed': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'source_data_json': ('django.db.models.fields.TextField', [], {}),
            'start_line_number': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'task_model_path': ('django.db.models.fields.CharField', [], {'max_length': '500'}),
            'task_pk': ('django.db.models.fields.PositiveIntegerField', [], {}),
            'total_rows': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'})
        },
        u'osmosis.importsharderror': {
            'Meta': {'object_name': 'ImportShardError'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'line': ('django.db.models.fields.TextField', [], {}),
            'shard': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['osmosis.ImportShard']"})
        },
        u'osmosis.importtask': {
            'Meta': {'object_name': 'ImportTask'},
            'error_csv': ('django.db.models.fields.files.FileField', [], {'max_length': '1023', 'null': 'True'}),
            'error_csv_filename': ('django.db.models.fields.CharField', [], {'max_length': '1023'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model_path': ('django.db.models.fields.CharField', [], {'max_length': '500'}),
            'row_count': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'shard_count': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'shards_error_csv_written': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'shards_processed': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'source_data': ('django.db.models.fields.files.FileField', [], {'max_length': '1023'}),
            'status': ('django.db.models.fields.CharField', [], {'default': "'pending'", 'max_length': '32'})
        }
    }

    complete_apps = ['osmosis']