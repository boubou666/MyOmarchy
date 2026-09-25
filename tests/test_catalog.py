import io
from pathlib import Path
import tarfile
import unittest

import catalog


class CatalogTests(unittest.TestCase):
    def test_pacman_database_names_descriptions_and_search(self):
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
            description = b"%NAME%\nfirefox\n\n%VERSION%\n155-1\n\n%DESC%\nA web browser\n\n"
            member = tarfile.TarInfo("firefox-155-1/desc")
            member.size = len(description)
            archive.addfile(member, io.BytesIO(description))
        packages = catalog.parse_database(archive_bytes.getvalue(), "extra")
        self.assertEqual(packages, [{"name": "firefox", "version": "155-1",
                                     "description": "A web browser", "repo": "extra"}])
        search = catalog.Catalog(Path("nonexistent-catalog.json"))
        search.packages = packages
        self.assertEqual(search.search("FIRE")[0]["name"], "firefox")
        self.assertEqual(search.search("browser")[0]["name"], "firefox")


if __name__ == "__main__":
    unittest.main()
