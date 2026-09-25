import io
import tarfile
import unittest

import verify_iso


class VerifyIsoTests(unittest.TestCase):
    def test_repository_database_exposes_archive_and_checksum(self):
        content = (b"%FILENAME%\nfirefox-1-1-x86_64.pkg.tar.zst\n\n"
                   b"%NAME%\nfirefox\n\n%SHA256SUM%\nabc123\n")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            item = tarfile.TarInfo("firefox-1-1/desc")
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
        entries = verify_iso.repo_entries(buffer.getvalue())
        self.assertEqual(entries["firefox"]["FILENAME"], "firefox-1-1-x86_64.pkg.tar.zst")
        self.assertEqual(entries["firefox"]["SHA256SUM"], "abc123")


if __name__ == "__main__":
    unittest.main()
