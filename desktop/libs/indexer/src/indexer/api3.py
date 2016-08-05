#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging

from django.utils.translation import ugettext as _

from desktop.lib.django_util import JsonResponse

from indexer.smart_indexer import Indexer
from indexer.controller import CollectionManagerController
from notebook.api import get_sample_data
from notebook.connectors.base import get_api

LOG = logging.getLogger(__name__)

def _escape_white_space_characters(s, inverse = False):
  MAPPINGS = {
    "\n":"\\n",
    "\t":"\\t",
    "\r":"\\r",
    " ":"\\s"
  }

  to = 1 if inverse else 0
  from_ = 0 if inverse else 1

  for pair in MAPPINGS.iteritems():
    s = s.replace(pair[to], pair[from_]).encode('utf-8')

  return s

def _convert_format(format_dict, inverse=False):
  for field in format_dict:
    if isinstance(format_dict[field], basestring):
      format_dict[field] = _escape_white_space_characters(format_dict[field], inverse)

def guess_format(request):
  file_format = json.loads(request.POST.get('fileFormat', '{}'))

  if file_format['inputFormat'] == 'file':
    indexer = Indexer(request.user, request.fs)
    stream = request.fs.open(file_format["path"])
    format_ = indexer.guess_format({
      "file":{
        "stream": stream,
        "name": file_format['path']
        }
      })
    _convert_format(format_)
  elif file_format['inputFormat'] == 'table' or file_format['inputFormat'] == 'query':
    print 'get table format'
    format_ = {"quoteChar": "\"", "recordSeparator": "\\n", "type": "csv", "hasHeader": True, "fieldSeparator": ","}

  return JsonResponse(format_)

def guess_field_types(request):
  file_format = json.loads(request.POST.get('fileFormat', '{}'))
  
  if file_format['inputFormat'] == 'file':
    indexer = Indexer(request.user, request.fs)
    stream = request.fs.open(file_format["path"])
    _convert_format(file_format["format"], inverse=True)

    format_ = indexer.guess_field_types({
      "file":{
        "stream":stream,
        "name":file_format['path']
        },
      "format":file_format['format']
    })
  elif file_format['inputFormat'] == 'table':
    sample = get_api(request, {'type': 'hive'}).get_sample_data({'type': 'hive'}, database='default', table='sample_07')
    format_ = {
        "sample": sample['rows'][:4],
        "columns": [
            {"operations": [], "name": col, "required": False, "keep": True, "unique": False, "type": "string"}
            for col in sample['headers']
        ]
    }

  return JsonResponse(format_)

def index_file(request):
  file_format = json.loads(request.POST.get('fileFormat', '{}'))
  _convert_format(file_format["format"], inverse=True)
  collection_name = file_format["name"]

  indexer = Indexer(request.user, request.fs)
  unique_field = indexer.get_unique_field(file_format)
  is_unique_generated = indexer.is_unique_generated(file_format)

  schema_fields = indexer.get_kept_field_list(file_format['columns'])
  if is_unique_generated:
    schema_fields += [{"name": unique_field, "type": "string"}]

  morphline = indexer.generate_morphline_config(collection_name, file_format, unique_field)

  collection_manager = CollectionManagerController(request.user)
  if not collection_manager.collection_exists(collection_name):
    collection_manager.create_collection(collection_name, schema_fields, unique_key_field=unique_field)

  job_id = indexer.run_morphline(collection_name, morphline, file_format["path"])

  return JsonResponse({"jobId": job_id})
