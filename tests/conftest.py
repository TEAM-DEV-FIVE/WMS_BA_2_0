import gc
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.credentials import hash_password
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import migrate


@pytest.fixture(autouse=True)
def isolated_desktop_data(monkeypatch, tmp_path):
    # Tests never open the real operator's device identity or recovery journal.
    monkeypatch.setenv("WMS_LOCAL_DATA_DIR", str(tmp_path / "desktop-data"))


@pytest.fixture(autouse=True)
def collect_gui_on_main_thread(request):
    yield
    if request.node.get_closest_marker("gui"):
        gc.collect()


@pytest.fixture
def empty_database():
    value = os.environ.get("WMS_TEST_DATABASE_URL")
    if not value:
        pytest.fail("Integration tests require a disposable PostgreSQL database; run scripts/check_application.py")
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").startswith("wms_test_"):
        pytest.fail("WMS_TEST_DATABASE_URL must point to PostgreSQL and a wms_test_* database")
    name = "wms_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = make_engine(Settings(database_url=url.set(database=name).render_as_string(hide_password=False)))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def database(empty_database):
    migrate(empty_database)
    return empty_database


@pytest.fixture
def actor(database):
    actor_id = uuid4()
    with database.begin() as connection:
        connection.execute(text("""
            INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
            VALUES (:id,'fixture-user','Test user','not-a-login-hash',true,0,now())
        """), {"id": actor_id})
    return actor_id


PASSWORD = "Test-only-password-2026!"


@pytest.fixture
def iam(database):
    settings = Settings(database_url="postgresql+psycopg://localhost/unused", mfa_encryption_key=Fernet.generate_key().decode())
    app = create_app(settings, engine=database)
    service = app.state.identity
    class Fixture:
        def __init__(self):
            self.engine = database
            self.service = service
            self.now = datetime(2026, 10, 2, 14, 0, tzinfo=UTC)
            self.device = uuid4()
        def advance(self, seconds=31):
            self.now += timedelta(seconds=seconds)
        def user(self, username="operator", *, mfa=False):
            user_id = uuid4()
            with database.begin() as connection:
                connection.execute(text("""INSERT INTO wms.app_user
                    VALUES (:id,:name,:name,:password,true,0,:now)"""),
                                   {"id": user_id, "name": username, "password": hash_password(PASSWORD), "now": self.now})
                secret = None
                if mfa:
                    secret = pyotp.random_base32()
                    connection.execute(text("""INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext,verified_at)
                        VALUES (:id,:user,'TOTP',:cipher,:now)"""),
                                       {"id": uuid4(), "user": user_id, "cipher": service.cipher().encrypt(secret.encode()).decode(), "now": self.now})
            return user_id, secret
        def grant(self, user, role, warehouse=None, *, scope=None, until=None):
            grant_id = uuid4()
            with database.begin() as connection:
                connection.execute(text("""INSERT INTO wms.user_role_grant
                    (id,user_id,role_id,scope_kind,warehouse_id,valid_from,valid_until,granted_by)
                    SELECT :id,:user,id,:scope,:warehouse,:now,:until,:user FROM wms.role WHERE code=:role"""),
                                   {"id": grant_id, "user": user, "scope": scope or ("WAREHOUSE" if warehouse else "GLOBAL"),
                                    "warehouse": warehouse, "now": self.now-timedelta(days=1), "until": until, "role": role})
            return grant_id
        def warehouse(self, code):
            warehouse = uuid4()
            with database.begin() as connection:
                connection.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:id,:code,:code,true)"), {"id": warehouse, "code": code})
            return warehouse
        def login(self, username="operator", secret=None):
            response = self.client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD, "device_id": str(self.device)})
            assert response.status_code == 200, response.text
            if secret:
                response = self.client.post("/api/v1/auth/mfa", json={"challenge_token": response.json()["challenge_token"],
                    "code": pyotp.TOTP(secret).at(self.now)})
                assert response.status_code == 200, response.text
            return response.json()
        def headers(self, tokens):
            return {"Authorization": "Bearer " + tokens["access_token"]}
        def document(self, warehouse, creator):
            doc, uom, product = uuid4(), uuid4(), uuid4()
            with database.begin() as connection:
                connection.execute(text("""INSERT INTO wms.document
                    (id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes)
                    VALUES (:id,:number,'PO','SUBMITTED',:warehouse,:date,:creator,:now,1,'{}')"""),
                                   {"id": doc, "number": str(doc), "warehouse": warehouse, "creator": creator, "date": self.now.date(), "now": self.now})
                connection.execute(text("INSERT INTO wms.uom VALUES (:id,:code,'Unit',0)"), {"id": uom, "code": uom.hex[:20]})
                connection.execute(text("""INSERT INTO wms.product
                    (id,sku,name,base_uom_id,tracking,expiry_required,is_active,version,attributes)
                    VALUES (:id,:sku,'Fixture',:uom,'NONE',false,true,1,'{}')"""), {"id": product, "sku": str(product), "uom": uom})
                connection.execute(text("""INSERT INTO wms.document_line
                    (id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,reference_unit_price,owner_id)
                    VALUES (:id,:doc,1,:product,:uom,5,1,5,99,'00000000-0000-4000-8000-000000000001')"""), {"id": uuid4(), "doc": doc, "product": product, "uom": uom})
            return doc
    fixture = Fixture()
    service.clock = lambda: fixture.now
    with TestClient(app) as client:
        fixture.client = client
        yield fixture


pytest_plugins = ["scripts.pytest_checks"]
