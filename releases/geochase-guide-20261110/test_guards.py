import hashlib
from pathlib import Path
import tempfile
import unittest
from reconstruct import require_file, require_publication

class Guards(unittest.TestCase):
    def test_explicit_request_allows_publication_without_claiming_visual_qa(self):
        manifest = {'qa': {'approved': False, 'status': 'visual-verification-pending'},
                    'archive': {'sha256': 'a'},
                    'publication': {'user_requested_publication': True, 'archiveSha256': 'a',
                                    'recordedAtUtc': '2026-11-10T20:16:09Z', 'request': 'update download'}}
        require_publication(manifest)
        self.assertIs(manifest['qa']['approved'], False)

    def test_explicit_request_for_other_zip_is_rejected(self):
        with self.assertRaises(ValueError):
            require_publication({'qa': {'approved': False}, 'archive': {'sha256': 'a'},
                        'publication': {'user_requested_publication': True, 'archiveSha256': 'b',
                                        'recordedAtUtc': '2026-11-10T20:16:09Z', 'request': 'update download'}})

    def test_pending_qa_blocks_release(self):
        with self.assertRaises(ValueError):
            require_publication({'qa': {'approved': False}, 'archive': {'sha256': 'a'}})

    def test_qa_for_different_archive_blocks_release(self):
        with self.assertRaises(ValueError):
            require_publication({'qa': {'approved': True, 'archiveSha256': 'b'}, 'archive': {'sha256': 'a'}})

    def test_corrupted_bytes_block_reconstruction(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'payload'
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                require_file(path, {'bytes': 7, 'sha256': hashlib.sha256(b'correct').hexdigest()})

if __name__ == '__main__':
    unittest.main()
