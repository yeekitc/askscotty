from rest_framework import serializers


class AskSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000)


class CitationSerializer(serializers.Serializer):
    title = serializers.CharField()
    url = serializers.URLField(required=False, allow_blank=True)
    source = serializers.CharField()
    indexed_at = serializers.CharField(required=False, allow_blank=True)
    verified_at = serializers.CharField(required=False, allow_blank=True)


class AskResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    citations = CitationSerializer(many=True)
    modes_used = serializers.ListField(child=serializers.CharField())
    note = serializers.CharField()
