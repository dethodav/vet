# -*- coding: utf-8 -*-
# Copyright (C) Duncan Macleod (2014-2015)
#
# This file is part of GWpy VET.
#
# GWpy VET is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# GWpy VET is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with GWpy VET.  If not, see <http://www.gnu.org/licenses/>.

"""Core evaluation methods for GWpy VET
"""

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

from gwpy.segments import DataQualityFlag
from gwpy.table.utils import get_row_value

from . import version
from .metric import Metric
from .metric.registry import get_metric

__author__ = 'Duncan Macleod <duncan.macleod@ligo.org>'
__version__ = version.version


def evaluate_flag(flag, triggers=None, metrics=['deadtime'], injections=None):
    """Evaluate the performance of a set of a `~gwpy.segments.DataQualityFlag`

    Parameters
    ----------
    flag : `~gwpy.segments.DataQualityFlag`
        the data-quality flag to be tested
    triggers : `~glue.ligolw.table.Table`, optional
        the set of analysis event triggers against which to test
    metrics : `list`, optional
        the list of `Metrics <~gwpy.toolkits.vet.Metric>`
    injections : `~glue.ligolw.table.Table`, `~gwpy.segments.SegmentList`, optional
        a list of injections, or injection segments, against which to test
        flag safety

    Returns
    -------
    results, after : `OrderedDict`, `~glue.ligolw.table.Table`
        the results of each metric test, and the triggers after vetoes have
        been applied (or `None` if not given)
    """
    # format as flag
    if not isinstance(flag, DataQualityFlag):
        flag = DataQualityFlag(active=flag)

    # apply vetoes to triggers
    if triggers is not None:
        after = triggers.copy()
        for t in triggers:
            if float(get_row_value(t, 'time')) in flag.active:
                continue
            after.append(t)
    else:
        after = None

    # test each metric
    out = OrderedDict()
    for metric in metrics:
        if isinstance(metric, Metric):
            _metric = metric
        else:
            _metric = get_metric(metric)
        if _metric.name.lower() == 'safety':
            out[metric] = _metric(flag, injections)
        elif _metric.needs_triggers:
            out[metric] = _metric(flag, triggers, after=after)
        else:
            out[metric] = _metric(flag)

    return out, after
