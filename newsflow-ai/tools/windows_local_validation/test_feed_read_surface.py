"""Focused pure URL contracts; no app, database, native or network execution."""
import unittest
from http_surface import request_allowed

class FeedReadSurface(unittest.TestCase):
    def test_exact_get(self):self.assertTrue(request_allowed('GET','/api/feed-batches'))
    def test_other_methods_remain_denied(self):
        for method in ('HEAD','POST','PUT','PATCH','DELETE','OPTIONS'):
            with self.subTest(method=method):self.assertFalse(request_allowed(method,'/api/feed-batches'))
    def test_no_prefix_grant(self):
        for path in ('/api/feed-batches/','/api/feed-batches/1','/api/feed-batches/1/step','/api/feed-batches/1/items/1/file','/api/feed-batches/defaults','/api/feed-batches%2f1'):
            with self.subTest(path=path):self.assertFalse(request_allowed('GET',path))
    def test_no_generation_publication_or_account_write(self):
        for path in ('/api/feed-batches','/api/feed-batches/defaults','/api/feed-batches/1/step','/api/feed-batches/1/change','/api/feed-batches/1/items/1/review','/publishing/drafts/1/validate','/youtube/publish/1','/oauth/connect'):
            with self.subTest(path=path):self.assertFalse(request_allowed('POST',path))
    def test_existing_local_save_surface_preserved(self):
        self.assertTrue(request_allowed('POST','/ai/drafts/1'))
        self.assertTrue(request_allowed('POST','/api/samples/character-robot/visibility'))
        self.assertTrue(request_allowed('GET','/api/studio/modules/images'))
if __name__=='__main__':unittest.main(verbosity=2)
