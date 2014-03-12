#    Copyright (c) 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import eventlet
import json
import socket
import time

from muranoapi.api import v1
from muranoapi.api.v1 import statistics
from muranoapi.common import config

from muranoapi.db.services import stats as db_stats
from muranoapi.openstack.common.gettextutils import _  # noqa
from muranoapi.openstack.common import log as logging
from muranoapi.openstack.common import service


conf = config.CONF.stats
log = logging.getLogger(__name__)


class StatsCollectingService(service.Service):
    def __init__(self):
        super(StatsCollectingService, self).__init__()
        statistics.init_stats()
        self._hostname = socket.gethostname()
        self._stats_db = db_stats.Statistics()
        self._prev_time = time.time()

    def start(self):
        super(StatsCollectingService, self).start()
        self.tg.add_thread(self._collect_stats_loop)

    def stop(self):
        self(StatsCollectingService, self).stop()

    def _collect_stats_loop(self):
        period = conf.period * 60
        while True:
            self.update_stats()
            eventlet.sleep(period)

    def update_stats(self):
        log.debug(_("Updating statistic information."))
        log.debug("Stats object: %s" % v1.stats)
        log.debug("Stats: Requests:%s  Errors: %s Ave.Res.Time %2.4f\n"
                  "Per tenant: %s" %
                  (v1.stats.request_count,
                   v1.stats.error_count,
                   v1.stats.average_time,
                   v1.stats.requests_per_tenant))
        try:
            stats = self._stats_db.get_stats_by_host(self._hostname)
            if stats is None:
                self._stats_db.create(self._hostname,
                                      v1.stats.request_count,
                                      v1.stats.error_count,
                                      v1.stats.average_time,
                                      v1.stats.requests_per_tenant)
                return

            now = time.time()
            t_delta = now - self._prev_time
            requests_per_second = (v1.stats.request_count -
                                   stats.request_count) / t_delta
            errors_per_second = (v1.stats.error_count -
                                 stats.error_count) / t_delta
            self._prev_time = now
            stats.request_count = v1.stats.request_count
            stats.error_count = v1.stats.error_count
            stats.average_response_time = v1.stats.average_time
            stats.requests_per_tenant = json.dumps(v1.stats.
                                                   requests_per_tenant)
            stats.requests_per_second = requests_per_second
            stats.errors_per_second = errors_per_second
            self._stats_db.update(self._hostname, stats)
        except Exception as e:
            log.error(_("Failed to get statistics object "
                        "form a database. %s" % e))