#
# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.
#
import os
from hashlib import md5
import asyncio
from functools import partial
import logging

import aioboto3
from aiobotocore.utils import logger as aws_logger

from connectors.source import BaseDataSource
from connectors.logger import logger, set_extra_logger


SUPPORTED_CONTENT_TYPE = [
    "text/plain",
]
SUPPORTED_FILETYPE = [".py", ".rst", ".rb", ".sh", ".md", ".txt"]
ONE_MEGA = 1048576


class S3DataSource(BaseDataSource):
    """Amazon S3"""

    def __init__(self, connector):
        super().__init__(connector)
        self.session = aioboto3.Session()
        self.loop = asyncio.get_event_loop()
        set_extra_logger(aws_logger, log_level=logging.INFO, prefix="S3")
        set_extra_logger("aioboto3.resources", log_level=logging.INFO, prefix="S3")

    async def close(self):
        await self.dl_client.close()

    async def ping(self):
        return True

    async def _get_content(self, key, timestamp):
        # reuse the same for all files

        logger.debug(f"Downloading {key}")
        async with self.session.client(
            "s3", region_name=self.configuration["region"]
        ) as s3:
            # XXX limit the size
            resp = await s3.get_object(Bucket=self.configuration["bucket"], Key=key)
            await asyncio.sleep(0)
            data = ""
            while True:
                chunk = await resp["Body"].read(ONE_MEGA)
                await asyncio.sleep(0)
                if not chunk:
                    break
                data += chunk.decode("utf8")
            logger.debug(f"Downloaded {len(data)} for {key}")
            return {"timestamp": timestamp, "text": data}

    async def get_docs(self):
        async with self.session.resource(
            "s3", region_name=self.configuration["region"]
        ) as s3:
            bucket = await s3.Bucket(self.configuration["bucket"])
            await asyncio.sleep(0)

            async for obj_summary in bucket.objects.all():

                doc_id = md5(obj_summary.key.encode("utf8")).hexdigest()
                last_modified = await obj_summary.last_modified
                await asyncio.sleep(0)

                key = obj_summary.key
                doc = {
                    "_id": doc_id,
                    "filename": key,
                    "size": await obj_summary.size,
                    "timestamp": last_modified.isoformat(),
                }

                async def _download(doc_id, key, timestamp=None, doit=None):
                    if not doit:
                        return

                    # XXX check the checksum_crc32 of the file
                    # obj = await obj_summary.Object()  # XXXX expensive
                    # content_type = await obj.content_type

                    if (
                        # content_type not in SUPPORTED_CONTENT_TYPE
                        os.path.splitext(key)[-1]
                        not in SUPPORTED_FILETYPE
                    ):
                        logger.debug(f"{key} can't be extracted")
                        return

                    content = await self._get_content(key, timestamp)
                    content["_id"] = doc_id
                    return content

                yield doc, partial(_download, doc_id, key)

    @classmethod
    def get_default_configuration(cls):
        return {
            "bucket": {
                "value": "ent-search-ingest-dev",
                "label": "AWS Bucket",
                "type": "str",
            },
            "region": {
                "value": "us-west-2",
                "label": "AWS Region",
                "type": "str",
            },
        }
