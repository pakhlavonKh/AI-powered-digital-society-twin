"""Synthetic-only schema tests, runnable with unittest or pytest."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from societytwin.university import SCHEMA_VERSION, SchemaVersionError, connect, initialize_database


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "university.sqlite3"
        initialize_database(self.path)
        self.conn = connect(self.path)
        self.addCleanup(self.conn.close)
        self.conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version, notes) VALUES (?, ?, ?, ?, ?, ?)",
                          ("s1", "synthetic.xlsx", "a" * 64, "2099-01-01T00:00:00Z", "test-v1", None))
        self.conn.execute("INSERT INTO universities (university_id, snapshot_id, university_key, "
                          "name_original, name_normalized) VALUES (1, 's1', 'synthetic-u', 'Test U', 'test u')")
        self.program(1, "00123")
        self.conn.commit()

    def program(self, program_id, code, snapshot="s1"):
        self.conn.execute("INSERT INTO programs (program_id, snapshot_id, university_id, "
                          "program_code, name_original, source_sheet, source_row) VALUES (?, ?, 1, ?, 'Synthetic program', 'Test', 2)",
                          (program_id, snapshot, code))

    def admissions(self, year=2099, quota=None, placed=None, snapshot="s1", program=1):
        self.conn.execute("INSERT INTO annual_admissions (program_id, snapshot_id, admission_year, "
                          "quota, placed_students, source_sheet, source_row) VALUES (?, ?, ?, ?, ?, 'Test', 2)",
                          (program, snapshot, year, quota, placed))

    def tuition(self, amount, year=2099):
        self.conn.execute("INSERT INTO annual_tuition (program_id, snapshot_id, academic_year_start, "
                          "net_amount_minor, currency, source_sheet, source_row) "
                          "VALUES (1, 's1', ?, ?, 'TRY', 'Test', 2)", (year, amount))

    def test_initialization(self):
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 6)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_idempotence_preserves_data(self):
        before = list(self.conn.iterdump())
        initialize_database(self.path)
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.admissions(program=999)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM universities WHERE university_id=1")

    def test_program_code_uniqueness_and_text(self):
        self.assertEqual(self.conn.execute("SELECT program_code FROM programs").fetchone()[0], "00123")
        with self.assertRaises(sqlite3.IntegrityError):
            self.program(2, "00123")
        self.program(3, "123")

    def test_annual_uniqueness(self):
        self.admissions()
        with self.assertRaises(sqlite3.IntegrityError):
            self.admissions()
        self.admissions(year=2098)
        self.tuition(0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.tuition(10)
        self.tuition(10, year=2098)

    def test_null_and_zero(self):
        self.admissions(quota=None, placed=0)
        row = self.conn.execute("SELECT quota, placed_students, success_rank FROM annual_admissions").fetchone()
        self.assertEqual(tuple(row), (None, 0, None))
        self.tuition(None)
        self.tuition(0, year=2098)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT net_amount_minor FROM annual_tuition ORDER BY academic_year_start")], [0, None])

    def test_invalid_quota(self):
        for value in (-1, 1.5, "unknown"):
            with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                self.admissions(quota=value)

    def test_invalid_tuition(self):
        for value in (-1, 1.5, "unknown"):
            with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                self.tuition(value)

    def test_source_references_and_snapshot_isolation(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.admissions(snapshot="missing")
        self.conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version, notes) VALUES (?, ?, ?, ?, ?, ?)",
                          ("s2", "synthetic-2.xlsx", "b" * 64, "2099-01-02T00:00:00Z", "test-v1", None))
        with self.assertRaises(sqlite3.IntegrityError):
            self.admissions(snapshot="s2")
        with self.assertRaises(sqlite3.IntegrityError):
            self.program(2, "00123", snapshot="s2")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM source_snapshots WHERE snapshot_id='s1'")

    def test_snapshot_hash_uniqueness_and_validation(self):
        for checksum in ("a" * 64, "bad-hash"):
            with self.subTest(checksum=checksum), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version, notes) VALUES (?, ?, ?, ?, ?, ?)",
                                  ("s2", "other.xlsx", checksum, "2099-01-01", "v1", None))

    def test_language_english(self):
        self.assert_language("İngilizce")

    def test_language_turkish(self):
        self.assert_language("Türkçe")

    def test_language_unspecified_is_null(self):
        self.assertIsNone(self.conn.execute("SELECT teaching_language FROM programs").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE programs SET teaching_language=''")

    def test_language_no_inference_or_standardization(self):
        self.conn.execute("UPDATE programs SET name_original='Synthetic English department'")
        self.assert_language(None)
        for label in ("FRANÇAIS", "  İngilizce  ", "türkçe", "Other label"):
            self.assert_language(label)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(programs)")}
        self.assertNotIn("teaching_language_normalized", columns)

    def assert_language(self, value):
        self.conn.execute("UPDATE programs SET teaching_language=?", (value,))
        self.assertEqual(self.conn.execute("SELECT teaching_language FROM programs").fetchone()[0], value)

    def test_placed_count_not_capped(self):
        self.admissions(quota=0, placed=2)
        self.assertEqual(self.conn.execute("SELECT placed_students FROM annual_admissions").fetchone()[0], 2)

    def test_full_and_net_tuition_are_independent_observations(self):
        self.tuition(None)
        self.conn.execute("UPDATE annual_tuition SET full_amount_minor=123456, fee_basis='source label'")
        self.assertEqual(tuple(self.conn.execute("SELECT full_amount_minor, net_amount_minor FROM annual_tuition").fetchone()), (123456, None))
        for value in (-1, 1.25, "invalid"):
            with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute("UPDATE annual_tuition SET full_amount_minor=?", (value,))

    def test_quality_issue_references_and_uniqueness(self):
        sql = ("INSERT INTO data_quality_issues (snapshot_id, issue_key, severity, issue_code, message, program_id) "
               "VALUES ('s1', 'Test:2:quota:missing', 'warning', 'missing', 'Synthetic issue', ?)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (999,))
        self.conn.execute(sql, (1,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (1,))

    def test_unsupported_version(self):
        self.conn.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(SchemaVersionError, "999"):
            initialize_database(self.path)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 999)

    def test_nonempty_unversioned_database(self):
        self.conn.execute("PRAGMA user_version=0")
        with self.assertRaisesRegex(SchemaVersionError, "nonempty"):
            initialize_database(self.path)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM programs").fetchone()[0], 1)

    def test_missing_table_is_not_silently_recreated(self):
        self.conn.execute("DROP TABLE data_quality_issues")
        self.conn.commit()
        with self.assertRaisesRegex(SchemaVersionError, "missing tables"):
            initialize_database(self.path)

    def test_schema_definition_mismatch(self):
        self.conn.execute("ALTER TABLE programs ADD COLUMN unwanted TEXT")
        self.conn.commit()
        with self.assertRaisesRegex(SchemaVersionError, "definitions"):
            initialize_database(self.path)

    def test_failed_initialization_rolls_back(self):
        path = Path(self.temp.name) / "failed.sqlite3"
        with patch("societytwin.university.db.SCHEMA", "CREATE TABLE partial (id INTEGER); INVALID SQL;"):
            with self.assertRaises(sqlite3.OperationalError):
                initialize_database(path)
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_snapshot_revision_can_reuse_program_code(self):
        self.conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version) "
                          "VALUES ('s2', 'revision.xlsx', ?, '2099-01-02', 'test-v1')", ("b" * 64,))
        self.conn.execute("INSERT INTO universities (university_id, snapshot_id, university_key, name_original, name_normalized) "
                          "VALUES (2, 's2', 'synthetic-u', 'Test U', 'test u')")
        self.conn.execute("INSERT INTO programs (program_id, snapshot_id, university_id, program_code, name_original, source_sheet, source_row) "
                          "VALUES (2, 's2', 2, '00123', 'Synthetic program', 'Test', 2)")
        self.admissions(snapshot="s2", program=2)
