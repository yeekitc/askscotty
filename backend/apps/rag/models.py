from django.db import models
from pgvector.django import VectorField


class CrawlSeed(models.Model):
    url = models.URLField(max_length=2000, unique=True)
    label = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.label


class Document(models.Model):
    url = models.URLField(max_length=2000, unique=True)
    title = models.CharField(max_length=500, blank=True)
    source_tier = models.CharField(max_length=50, default="public")
    # auto_now means fetched_at tracks when we last saw the content change, not
    # every crawl visit — unchanged pages are skipped without updating this field.
    fetched_at = models.DateTimeField(auto_now=True)
    content_hash = models.CharField(max_length=64, blank=True)
    robots_allowed = models.BooleanField(default=True)

    def __str__(self):
        return self.url


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    text = models.TextField()
    token_count = models.IntegerField(default=0)
    # dimensions=1536 must match EMBEDDING_MODEL (text-embedding-3-small default).
    # Changing the model means a new migration to drop and rebuild this column.
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    heading_path = models.CharField(max_length=500, blank=True)
    # Set when the embedding is written; None means pending reindex.
    indexed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.document.url}[{self.pk}]"
