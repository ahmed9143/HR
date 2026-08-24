# PostgreSQL production deployment

The application package remains SQLite-first for zero-configuration desktop use. This directory provides the production PostgreSQL schema and Docker service for a central server deployment.

The current Python application does not silently switch database engines because doing so would risk corrupting an existing SQLite deployment.
