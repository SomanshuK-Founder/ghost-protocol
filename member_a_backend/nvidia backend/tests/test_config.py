from sqlalchemy.engine import make_url

from app.config import Settings


def test_resolved_database_url_uses_mysql_settings_by_default():
    settings = Settings(
        _env_file=None,
        mysql_host="localhost",
        mysql_database="nvidia_app_test",
        mysql_user="integration user",
        mysql_password="example@password",
    )

    url = make_url(settings.resolved_database_url)

    assert url.drivername == "mysql+pymysql"
    assert url.username == "integration user"
    assert url.password == "example@password"
    assert url.host == "localhost"
    assert url.database == "nvidia_app_test"


def test_resolved_database_url_preserves_explicit_override():
    settings = Settings(_env_file=None, database_url="mysql+pymysql://user:pw@db:3307/app")

    assert settings.resolved_database_url == "mysql+pymysql://user:pw@db:3307/app"
