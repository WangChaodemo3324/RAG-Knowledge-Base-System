"""Upload security: path traversal, extension allowlist, name sanitization."""

from __future__ import annotations

import pytest

from backend.services.document_service import DocumentUploadError, safe_upload_filename


@pytest.mark.unit
class TestUploadFilenameSecurity:
    def test_path_traversal_forward_slashes(self):
        assert safe_upload_filename("../../etc/passwd.md") == "passwd.md"

    def test_path_traversal_backslashes(self):
        name = safe_upload_filename("..\\..\\windows\\system32\\evil.md")
        assert "/" not in name and "\\" not in name and ".." not in name
        assert name.endswith("evil.md")

    def test_dotdot_without_slash_rejected(self):
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("..")

    def test_hidden_double_dot_name(self):
        name = safe_upload_filename("..config.md")
        assert name == "..config.md"  # a file literally named ..config.md is safe (no dir sep)

    def test_extension_allowlist(self):
        assert safe_upload_filename("doc.PDF") == "doc.PDF"  # case-insensitive suffix
        assert safe_upload_filename("notes.md") == "notes.md"
        assert safe_upload_filename("a.txt") == "a.txt"
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("payload.exe")
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("invoice.md.exe")
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("script.sh")

    def test_special_chars_replaced(self):
        name = safe_upload_filename("a<b>:c|d?.md")
        for char in '<>:"|?*':
            assert char not in name
        assert name.endswith(".md")

    def test_empty_rejected(self):
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("")
        with pytest.raises(DocumentUploadError):
            safe_upload_filename("   ")
        with pytest.raises(DocumentUploadError):
            safe_upload_filename(None)

    def test_result_is_flat_name(self):
        name = safe_upload_filename("some/dir/tree/file.md")
        assert name == "file.md"
        from pathlib import Path

        assert Path(name).name == name
