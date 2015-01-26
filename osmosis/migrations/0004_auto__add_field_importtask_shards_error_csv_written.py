# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding field 'ImportTask.shards_error_csv_written'
        db.add_column(u'osmosis_importtask', 'shards_error_csv_written',
                      self.gf('django.db.models.fields.BooleanField')(default=False),
                      keep_default=False)


    def backwards(self, orm):
        # Deleting field 'ImportTask.shards_error_csv_written'
        db.delete_column(u'osmosis_importtask', 'shards_error_csv_written')


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
            'task': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['osmosis.ImportTask']"}),
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