from django.test import TestCase
import mock

from osmosis.models import ImportTask
from contextlib import nested

import StringIO

TEST_FILE_ONE = StringIO.StringIO()
TEST_FILE_ONE.write("""
Field1, Field2, Field3
value1, value2, value3
value1, value2, value3
value1, value2, value3
value1, value2, value3
value1, value2, value3
""".lstrip())
TEST_FILE_ONE.seek(0)

class ImportTaskTests(TestCase):
    def test_start_defers_process(self):
        patches = [
            mock.patch('google.appengine.ext.deferred.defer'),
        ]

        with nested(*patches) as (mock_def,):
            task = ImportTask()
            task.start()
            self.assertTrue(mock_def.called)

    def test_process_creates_shards(self):
        task = ImportTask()

        patches = [
            mock.patch('google.appengine.ext.deferred.defer'),
            mock.patch('osmosis.models.ImportShard.objects.create'),
            mock.patch('osmosis.models.ImportTask.objects.get', side_effect=lambda *args, **kwargs: task),
            mock.patch('osmosis.models.ImportTask.save')
        ]

        with nested(*patches) as (mock_def, mock_create, mock_get, mock_save):
            task.Osmosis.rows_per_shard = 1
            task.source_data = TEST_FILE_ONE
            task.process()
            self.assertEqual(5, mock_create.call_count)

    def test_shards_processed_updated(self):
        pass

    def test_finish_callback_deferred(self):
        pass

    def test_error_callback_on_error(self):
        pass

    def test_import_row_called_for_each_entity(self):
        pass

    def test_status_changed_when_process_starts(self):
        pass

    def test_status_changed_when_last_shard_finishes(self):
        pass

    def test_handle_error_called_if_import_row_throws_validation_error(self):
        pass

    def test_shard_process_reentrant(self):
        pass

    def test_process_reentrant(self):
        pass
