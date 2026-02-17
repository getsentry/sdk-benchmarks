from django.db import models


class World(models.Model):
    id = models.IntegerField(primary_key=True)
    randomnumber = models.IntegerField()

    class Meta:
        db_table = "world"
        managed = False


class Fortune(models.Model):
    id = models.IntegerField(primary_key=True)
    message = models.CharField(max_length=2048)

    class Meta:
        db_table = "fortune"
        managed = False
