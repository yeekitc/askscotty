from django.db import migrations, models
import django.db.models.deletion
import pgvector.django


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        # Enable pgvector in Postgres. RunSQL so a fresh DB applying migrations
        # never needs a manual setup step, and noop on reverse so the extension
        # is not dropped by migrate --fake-initial.
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="CrawlSeed",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("url", models.URLField(max_length=2000, unique=True)),
                ("label", models.CharField(max_length=100)),
                ("enabled", models.BooleanField(default=True)),
                ("last_crawled_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("url", models.URLField(max_length=2000, unique=True)),
                ("title", models.CharField(blank=True, max_length=500)),
                ("source_tier", models.CharField(default="public", max_length=50)),
                ("fetched_at", models.DateTimeField(auto_now=True)),
                ("content_hash", models.CharField(blank=True, max_length=64)),
                ("robots_allowed", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="Chunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("token_count", models.IntegerField(default=0)),
                ("embedding", pgvector.django.VectorField(blank=True, dimensions=1536, null=True)),
                ("heading_path", models.CharField(blank=True, max_length=500)),
                ("indexed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="rag.document",
                    ),
                ),
            ],
        ),
        # HNSW index for fast cosine-distance nearest-neighbour search.
        # Written as RunSQL rather than AddIndex so the exact opclass string is
        # unambiguous and we don't depend on pgvector-python exposing HnswIndex.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw "
                "ON rag_chunk USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64);"
            ),
            reverse_sql="DROP INDEX IF EXISTS chunk_embedding_hnsw;",
        ),
    ]
