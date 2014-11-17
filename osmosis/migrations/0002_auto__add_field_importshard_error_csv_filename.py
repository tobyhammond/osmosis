# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding field 'ImportShard.error_csv_filename'
        db.add_column(u'osmosis_importshard', 'error_csv_filename',
                      self.gf('django.db.models.fields.CharField')(default='', max_length=1023),
                      keep_default=False)


    def backwards(self, orm):
        # Deleting field 'ImportShard.error_csv_filename'
        db.delete_column(u'osmosis_importshard', 'error_csv_filename')


    models = {
        u'osmosis.importshard': {
            'Meta': {'object_name': 'ImportShard'},
            'complete': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'error_csv_filename': ('django.db.models.fields.CharField', [], {'max_length': '1023'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'last_row_processed': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'source_data_json': ('django.db.models.fields.TextField', [], {}),
            'start_line_number': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'task': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['osmosis.ImportTask']"}),
            'total_rows': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'})
        },
        u'osmosis.importtask': {
            'Meta': {'object_name': 'ImportTask'},
            'error_csv': ('django.db.models.fields.files.FileField', [], {'max_length': '1023', 'null': 'True'}),
            'error_csv_filename': ('django.db.models.fields.CharField', [], {'max_length': '1023'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model_path': ('django.db.models.fields.CharField', [], {'max_length': '500'}),
            'row_count': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'shard_count': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'shards_processed': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'}),
            'source_data': ('django.db.models.fields.files.FileField', [], {'max_length': '1023'}),
            'status': ('django.db.models.fields.CharField', [], {'default': "'pending'", 'max_length': '32'})
        }
    }

    complete_apps = ['osmosis']