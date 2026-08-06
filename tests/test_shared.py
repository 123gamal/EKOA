"""Unit tests for shared packages — ekoa_utils, ekoa_config, ekoa_types."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

# ── Shared Utils ─────────────────────────────────────────────────────────────


class TestDatetimeUtils:
    def test_utc_now_returns_aware_datetime(self):
        from ekoa_utils.datetime_utils import utc_now
        now = utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_utc_now_returns_recent_time(self):
        from ekoa_utils.datetime_utils import utc_now
        before = datetime.now(timezone.utc)
        now = utc_now()
        after = datetime.now(timezone.utc)
        assert before <= now <= after

    def test_format_iso_aware(self):
        from ekoa_utils.datetime_utils import format_iso
        dt = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = format_iso(dt)
        assert "2026-07-16" in result
        assert "+00:00" in result or "Z" in result

    def test_format_iso_naive(self):
        from ekoa_utils.datetime_utils import format_iso
        dt = datetime(2026, 7, 16, 12, 0, 0)
        result = format_iso(dt)
        # Naive datetime gets UTC assumed
        assert "+00:00" in result or "Z" in result

    def test_parse_iso_with_z(self):
        from ekoa_utils.datetime_utils import parse_iso
        dt = parse_iso("2026-07-16T12:00:00Z")
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026
        assert dt.month == 7

    def test_parse_iso_with_offset(self):
        from ekoa_utils.datetime_utils import parse_iso
        dt = parse_iso("2026-07-16T12:00:00+00:00")
        assert dt.tzinfo is not None

    def test_parse_iso_naive(self):
        from ekoa_utils.datetime_utils import parse_iso
        dt = parse_iso("2026-07-16T12:00:00")
        assert dt.tzinfo == timezone.utc

    def test_parse_iso_invalid_raises(self):
        from ekoa_utils.datetime_utils import parse_iso
        with pytest.raises(ValueError):
            parse_iso("not-a-date")

    def test_roundtrip(self):
        from ekoa_utils.datetime_utils import utc_now, format_iso, parse_iso
        original = utc_now()
        formatted = format_iso(original)
        parsed = parse_iso(formatted)
        assert abs((original - parsed).total_seconds()) < 1


class TestHashingUtils:
    def test_hash_password_returns_hash(self):
        from ekoa_utils.hashing import hash_password
        hashed = hash_password("my_secure_password")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$") or hashed.startswith("$2y$")
        assert len(hashed) > 20

    def test_verify_password_correct(self):
        from ekoa_utils.hashing import hash_password, verify_password
        hashed = hash_password("my_secure_password")
        assert verify_password("my_secure_password", hashed) is True

    def test_verify_password_incorrect(self):
        from ekoa_utils.hashing import hash_password, verify_password
        hashed = hash_password("my_secure_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_empty(self):
        from ekoa_utils.hashing import hash_password, verify_password
        hashed = hash_password("my_secure_password")
        assert verify_password("", hashed) is False

    def test_hash_different_each_time(self):
        from ekoa_utils.hashing import hash_password
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # bcrypt salts ensure different hashes

    def test_special_characters_in_password(self):
        from ekoa_utils.hashing import hash_password, verify_password
        pwd = "!@#$%^&*()_+-=[]{}|;':\",./<>?~`你好世界🌟"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_password_max_length(self):
        from ekoa_utils.hashing import hash_password, verify_password
        pwd = "a" * 72
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_password_beyond_max_length(self):
        from ekoa_utils.hashing import hash_password
        pwd = "a" * 100
        with pytest.raises(ValueError, match="cannot be longer than 72"):
            hash_password(pwd)


class TestTextUtils:
    def test_sanitize_text_normal(self):
        from ekoa_utils.text import sanitize_text
        result = sanitize_text("  Hello   World  ")
        assert result == "Hello World"

    def test_sanitize_text_unicode(self):
        from ekoa_utils.text import sanitize_text
        result = sanitize_text("Café\u00a0résumé")  # non-breaking space
        assert "Café" in result
        assert "résumé" in result

    def test_sanitize_text_newlines(self):
        from ekoa_utils.text import sanitize_text
        result = sanitize_text("Line1\n\nLine2\nLine3")
        assert result == "Line1 Line2 Line3"

    def test_sanitize_text_empty(self):
        from ekoa_utils.text import sanitize_text
        assert sanitize_text("") == ""

    def test_sanitize_text_whitespace_only(self):
        from ekoa_utils.text import sanitize_text
        assert sanitize_text("   \n\n   \t   ") == ""

    def test_truncate_text_short(self):
        from ekoa_utils.text import truncate_text
        assert truncate_text("Hello", max_length=100) == "Hello"

    def test_truncate_text_exact(self):
        from ekoa_utils.text import truncate_text
        assert truncate_text("Hello World", max_length=11) == "Hello World"

    def test_truncate_text_long(self):
        from ekoa_utils.text import truncate_text
        result = truncate_text("Hello World This Is Long", max_length=15)
        assert len(result) <= 15
        assert result.endswith("…")

    def test_truncate_text_word_boundary(self):
        from ekoa_utils.text import truncate_text
        # Should break at word boundary
        result = truncate_text("Hello beautiful world", max_length=12)
        assert "Hello" in result
        assert result.endswith("…")

    def test_truncate_text_custom_suffix(self):
        from ekoa_utils.text import truncate_text
        result = truncate_text("Hello World This Is Long", max_length=10, suffix="...")
        assert result.endswith("...")

    def test_truncate_text_empty(self):
        from ekoa_utils.text import truncate_text
        assert truncate_text("", max_length=10) == ""

    def test_truncate_text_very_short_max(self):
        from ekoa_utils.text import truncate_text
        result = truncate_text("Hello World", max_length=1)
        assert len(result) == 1

    def test_count_tokens_empty(self):
        from ekoa_utils.text import count_tokens
        assert count_tokens("") == 0

    def test_count_tokens_short(self):
        from ekoa_utils.text import count_tokens
        assert count_tokens("Hello world") >= 1

    def test_count_tokens_long(self):
        from ekoa_utils.text import count_tokens
        long_text = "word " * 1000
        assert count_tokens(long_text) > 10


# ── Shared Config ────────────────────────────────────────────────────────────


class TestSettings:
    def test_settings_defaults(self):
        from ekoa_config.settings import Settings
        settings = Settings(_env_file=None)
        assert settings.APP_NAME == "EKOA"
        assert settings.DEBUG is False
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 30

    def test_settings_env_override(self, monkeypatch):
        monkeypatch.setenv("APP_NAME", "TestEKOA")
        monkeypatch.setenv("JWT_SECRET_KEY", "custom-secret")
        from ekoa_config.settings import Settings
        settings = Settings()
        assert settings.APP_NAME == "TestEKOA"
        assert settings.JWT_SECRET_KEY == "custom-secret"

    def test_settings_debug_env(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        from ekoa_config.settings import Settings
        settings = Settings()
        assert settings.DEBUG is True

    def test_get_settings_is_singleton(self):
        from ekoa_config.settings import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


# ── Shared Types (Schema Validation) ─────────────────────────────────────────


class TestAuthSchemas:
    def test_login_request_valid(self):
        from ekoa_types.auth import LoginRequest
        req = LoginRequest(email="user@test.com", password="strong123")
        assert req.email == "user@test.com"
        assert req.password == "strong123"

    def test_login_request_invalid_email(self):
        from ekoa_types.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="not-email", password="strong123")

    def test_login_request_short_password(self):
        from ekoa_types.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="user@test.com", password="short")

    def test_login_request_empty_email(self):
        from ekoa_types.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="", password="strong123")

    def test_register_request_valid(self):
        from ekoa_types.auth import RegisterRequest
        req = RegisterRequest(email="new@test.com", password="strong123", full_name="Test User")
        assert req.email == "new@test.com"
        assert req.full_name == "Test User"

    def test_register_request_missing_full_name(self):
        from ekoa_types.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="new@test.com", password="strong123")

    def test_register_request_empty_full_name(self):
        from ekoa_types.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="new@test.com", password="strong123", full_name="")

    def test_register_request_with_org_name(self):
        from ekoa_types.auth import RegisterRequest
        req = RegisterRequest(email="org@test.com", password="strong123", full_name="T", organization_name="My Org")
        assert req.organization_name == "My Org"


class TestOrganizationSchemas:
    def test_organization_create_valid(self):
        from ekoa_types.organization import OrganizationCreate
        org = OrganizationCreate(name="Test Org", slug="test-org")
        assert org.name == "Test Org"
        assert org.slug == "test-org"

    def test_organization_create_invalid_slug_uppercase(self):
        from ekoa_types.organization import OrganizationCreate
        with pytest.raises(ValidationError):
            OrganizationCreate(name="Bad Org", slug="BAD-ORG")

    def test_organization_create_invalid_slug_special_chars(self):
        from ekoa_types.organization import OrganizationCreate
        with pytest.raises(ValidationError):
            OrganizationCreate(name="Bad Org", slug="test_org!")

    def test_organization_create_empty_name(self):
        from ekoa_types.organization import OrganizationCreate
        with pytest.raises(ValidationError):
            OrganizationCreate(name="", slug="empty-name")

    def test_organization_create_empty_slug(self):
        from ekoa_types.organization import OrganizationCreate
        with pytest.raises(ValidationError):
            OrganizationCreate(name="Test", slug="")

    def test_organization_create_with_description(self):
        from ekoa_types.organization import OrganizationCreate
        org = OrganizationCreate(name="Test", slug="test", description="My org desc")
        assert org.description == "My org desc"

    def test_organization_create_none_description(self):
        from ekoa_types.organization import OrganizationCreate
        org = OrganizationCreate(name="Test", slug="test")
        assert org.description is None


class TestWorkspaceSchemas:
    def test_workspace_create_valid(self):
        from ekoa_types.workspace import WorkspaceCreate
        import uuid
        ws = WorkspaceCreate(name="My Workspace", organization_id=uuid.uuid4())
        assert ws.name == "My Workspace"

    def test_workspace_create_empty_name(self):
        from ekoa_types.workspace import WorkspaceCreate
        import uuid
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="", organization_id=uuid.uuid4())


class TestDocumentSchemas:
    def test_document_status_values(self):
        from ekoa_types.document import DocumentStatus
        assert DocumentStatus.PENDING.value == "PENDING"
        assert DocumentStatus.PROCESSING.value == "PROCESSING"
        assert DocumentStatus.INDEXED.value == "INDEXED"
        assert DocumentStatus.FAILED.value == "FAILED"

    def test_document_base_valid(self):
        from ekoa_types.document import DocumentBase
        doc = DocumentBase(title="test.txt", content_type="text/plain")
        assert doc.title == "test.txt"
        assert doc.content_type == "text/plain"

    def test_document_base_default_content_type(self):
        from ekoa_types.document import DocumentBase
        doc = DocumentBase(title="test.txt")
        assert doc.content_type == "text/plain"

    def test_document_base_empty_title(self):
        from ekoa_types.document import DocumentBase
        with pytest.raises(ValidationError):
            DocumentBase(title="")


class TestChatSchemas:
    def test_chat_message_valid(self):
        from ekoa_types.chat import ChatMessage
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_chat_message_empty_content(self):
        from ekoa_types.chat import ChatMessage
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="")

    def test_chat_request_valid(self):
        from ekoa_types.chat import ChatRequest
        import uuid
        req = ChatRequest(workspace_id=uuid.uuid4(), message="Hello")
        assert req.message == "Hello"

    def test_chat_request_with_history(self):
        from ekoa_types.chat import ChatRequest, ChatMessage
        import uuid
        history = [ChatMessage(role="user", content="Hi"), ChatMessage(role="assistant", content="Hello!")]
        req = ChatRequest(workspace_id=uuid.uuid4(), message="Tell me more", history=history)
        assert len(req.history) == 2

    def test_chat_request_empty_message(self):
        from ekoa_types.chat import ChatRequest
        import uuid
        with pytest.raises(ValidationError):
            ChatRequest(workspace_id=uuid.uuid4(), message="")

    def test_chat_response_has_actions(self):
        from ekoa_types.chat import ChatResponse, AgentAction
        import uuid
        from datetime import datetime, timezone
        resp = ChatResponse(
            conversation_id=uuid.uuid4(),
            reply="Test response",
            actions=[AgentAction(tool_name="test", tool_input={})],
            created_at=datetime.now(timezone.utc),
        )
        assert len(resp.actions) == 1
        assert resp.actions[0].tool_name == "test"


class TestUserSchemas:
    def test_user_base_valid(self):
        from ekoa_types.user import UserBase
        user = UserBase(email="user@test.com", full_name="Test User")
        assert user.email == "user@test.com"
        assert user.full_name == "Test User"
        assert user.is_active is True

    def test_user_base_invalid_email(self):
        from ekoa_types.user import UserBase
        with pytest.raises(ValidationError):
            UserBase(email="invalid", full_name="Test")

    def test_user_base_empty_full_name(self):
        from ekoa_types.user import UserBase
        with pytest.raises(ValidationError):
            UserBase(email="user@test.com", full_name="")

    def test_user_create_short_password(self):
        from ekoa_types.user import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(email="user@test.com", full_name="Test", password="short")
