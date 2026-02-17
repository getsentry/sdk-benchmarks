import json
import random

from django.http import HttpResponse
from django.shortcuts import render

from .models import Fortune, World


def health(request):
    return HttpResponse("OK")


def json_view(request):
    data = json.dumps({"message": "Hello, World!"})
    return HttpResponse(data, content_type="application/json")


def db(request):
    row_id = random.randint(1, 10000)
    world = World.objects.get(id=row_id)
    data = json.dumps({"id": world.id, "randomNumber": world.randomnumber})
    return HttpResponse(data, content_type="application/json")


def queries(request):
    num_queries = request.GET.get("queries", "1")
    try:
        num_queries = int(num_queries)
    except (ValueError, TypeError):
        num_queries = 1
    num_queries = max(1, min(500, num_queries))

    worlds = []
    for _ in range(num_queries):
        row_id = random.randint(1, 10000)
        world = World.objects.get(id=row_id)
        worlds.append({"id": world.id, "randomNumber": world.randomnumber})

    data = json.dumps(worlds)
    return HttpResponse(data, content_type="application/json")


def fortunes(request):
    all_fortunes = list(Fortune.objects.all())
    all_fortunes.append(
        Fortune(id=0, message="Additional fortune added at request time.")
    )
    all_fortunes.sort(key=lambda f: f.message)
    return render(request, "fortunes.html", {"fortunes": all_fortunes})
