-- Optional per-user avatar; separate from credentials and grants.
CREATE TABLE wms.user_avatar (
    user_id uuid PRIMARY KEY REFERENCES wms.app_user(id),
    image_base64 text,
    version integer NOT NULL CHECK (version > 0),
    updated_at timestamptz NOT NULL,
    CHECK (image_base64 IS NULL OR octet_length(image_base64) BETWEEN 1 AND 350000)
);
