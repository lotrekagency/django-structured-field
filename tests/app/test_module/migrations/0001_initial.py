# Generated by Django 4.2.6 on 2024-01-10 10:44

from django.db import migrations, models
import structured.fields
import tests.app.test_module.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SimpleRelationModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='TestModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('structured_data', structured.fields.StructuredJSONField(default=tests.app.test_module.models.init_schema, schema=tests.app.test_module.models.TestSchema)),
            ],
        ),
    ]
