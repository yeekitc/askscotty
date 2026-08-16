from django.contrib import admin

from apps.rag.models import Chunk, CrawlSeed, Document


@admin.register(CrawlSeed)
class CrawlSeedAdmin(admin.ModelAdmin):
    list_display = ("label", "url", "enabled", "last_crawled_at")
    list_filter = ("enabled",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("url", "title", "fetched_at", "robots_allowed")
    search_fields = ("url", "title")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "heading_path", "token_count", "indexed_at")
    list_select_related = ("document",)
    raw_id_fields = ("document",)
