# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'ImportTask'
        db.create_table(u'osmosis_importtask', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('model_path', self.gf('django.db.models.fields.CharField')(max_length=500)),
            ('source_data', self.gf('django.db.models.fields.files.FileField')(max_length=1023)),
            ('error_csv', self.gf('django.db.models.fields.files.FileField')(max_length=1023, null=True)),
            ('error_csv_filename', self.gf('django.db.models.fields.CharField')(max_length=1023)),
            ('row_count', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('shard_count', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('shards_processed', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('status', self.gf('django.db.models.fields.CharField')(default='pending', max_length=32)),
        ))
        db.send_create_signal(u'osmosis', ['ImportTask'])

        # Adding model 'ImportShard'
        db.create_table(u'osmosis_importshard', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('task', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['osmosis.ImportTask'])),
            ('source_data_json', self.gf('django.db.models.fields.TextField')()),
            ('last_row_processed', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('total_rows', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('start_line_number', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('complete', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'osmosis', ['ImportShard'])


    def backwards(self, orm):
        # Deleting model 'ImportTask'
        db.delete_table(u'osmosis_importtask')

        # Deleting model 'ImportShard'
        db.delete_table(u'osmosis_importshard')


    models = {
        u'osmosis.importshard': {
            'Meta': {'object_name': 'ImportShard'},
            'complete': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
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