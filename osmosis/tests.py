from django.test import TestCase
import mock

from osmosis.models import ImportTask, ImportShard, ImportStatus
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

        task = ImportTask()

        shard1 = ImportShard(task=task, id=1, source_data_json="[{}]", total_rows=1, task_model_path="osmosis.ImportTask")
        shard2 = ImportShard(task=task, id=2, source_data_json="[{}]", total_rows=1, task_model_path="osmosis.ImportTask")

        def shard_get(*args, **kwargs):
            if kwargs.values()[0] == 1:
                return shard1
            else:
                return shard2

        with mock.patch('osmosis.models.ImportTask.import_row'):
            with mock.patch('osmosis.models.ImportTask.save'):
                with mock.patch('osmosis.models.ImportShard.save'):
                    with mock.patch('osmosis.models.ImportShard.objects.get', autospec=True, side_effect=shard_get):
                        with mock.patch('osmosis.models.ImportTask.objects.get', return_value=task):
                            shard1.process()

                            self.assertEqual(1, task.shards_processed)

                            shard1.process()
                            self.assertEqual(1, task.shards_processed) #If the shard retries, don't increment again

                            shard2.process()
                            self.assertEqual(2, task.shards_processed)

    def test_finish_callback_deferred(self):
        task = ImportTask(shard_count=1, shards_processed=1)

        with mock.patch('django.db.models.Model.save') as save_patch:
            with mock.patch('google.appengine.ext.deferred.defer') as def_patch:
                task.save()
                self.assertTrue(save_patch.called)

                task.status = ImportStatus.IN_PROGRESS
                task.save()

                self.assertTrue(def_patch.called)

            with mock.patch('google.appengine.ext.deferred.defer') as def_patch:
                task.save()
                self.assertFalse(def_patch.called) #Already been called, so shouldn't happen again


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
