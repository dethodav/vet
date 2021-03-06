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

"""Summary-page style tabs for GWpy VET
"""

import os

from glue.lal import Cache

from gwpy.plotter.tex import label_to_latex
from gwpy.time import Time

from gwsumm import html
from gwsumm.config import NoOptionError
from gwsumm.data import get_channel
from gwsumm.segments import (get_segments, format_padding)
from gwsumm.triggers import get_triggers
from gwsumm.tabs import get_tab, register_tab
from gwsumm.plot import (get_plot, get_column_label)
from gwsumm.utils import vprint
from gwsumm.state import ALLSTATE

from . import etg
from .core import evaluate_flag
from .triggers import (re_meta, veto_tag)
from .metric import get_metric

__author__ = 'Duncan Macleod <duncan.macleod@ligo.org>'

ParentTab = get_tab('default')


class FlagTab(ParentTab):
    """Tab for analysing veto performance

    Parameters
    ----------
    name : `str`
        the name of this analysis, either the name of the flag tested,
        of a descriptive name for the groups of flags
    start : `float`, `~gwpy.time.LIGOTimeGPS`
        the GPS start time of the analysis
    end : `float`, `~gwpy.time.LIGOTimeGPS`
        the GPS end time of the analysis
    flags : `list`, optional
        the list of data-quality flags to be tested. Each flag can be given
        as a name to be queryied from the segment database, or a 2-tuple of
        ``(name, sourcefile)``, to be read from file - the ``sourcefile``
        can then be any file format understood by
        :meth:`DataQualityFlag.read <gwpy.segments.DataQualityFlag.read>`
    metrics : `list`, optional
        the list of performance metrics to use
    channel : `str`, optional
        the name of the channel who's triggers are to be used to test
        event-trigger performance
    etg : `str`, optional
        the name of the event-trigger-generator for the above `channel`
    format : `str`, optional
        the name of the input event file format
    intersection : `bool`, optional, default: `False`
        use the intersection of segments from all flags, otherwise use the
        union
    **kwargs
        other keyword arguments to set up this tab get passed to the
        `DataTab` constructor
    """
    type = 'veto-flag'

    def __init__(self, name,
                 flags=[],
                 metrics=[],
                 channel=None, etg=None, format=None,
                 intersection=False,
                 labels=None,
                 segmentfile=None,
                 minseglength=0,
                 padding=(0, 0),
                 plotdir=os.curdir, states=list([ALLSTATE]), **kwargs):
        if len(flags) == 0:
            flags = [name]
            if isinstance(name, tuple):
                name = name[0]
        super(FlagTab, self).__init__(
            name, states=states, **kwargs)
        self.flags = list(flags)
        self.segmentfile = segmentfile
        self.minseglength = minseglength
        self.labels = labels or map(str, self.flags)
        self.metrics = metrics
        self.channel = channel and get_channel(channel) or None
        self.etg = etg
        self.etgformat = format
        self.intersection = intersection
        self.padding = format_padding(self.flags, padding)
        if intersection:
            self.metaflag = '&'.join(map(str, self.flags))
        else:
            self.metaflag = '|'.join(map(str, self.flags))
        # make space for the results
        self.results = {}
        # configure default plots
        if not len(self.plots):
            self.init_plots(plotdir=plotdir)

    @classmethod
    def from_ini(cls, config, section, **kwargs):
        """Parse a new tab from a `ConfigParser` section
        """
        # get list of flags and source segmentfile
        kwargs.setdefault(
            'flags', [f.strip('\n ') for f in
                      config.get(section, 'flags').split(',')])
        try:
            kwargs.setdefault('segmentfile', config.get(section, 'segmentfile'))
        except NoOptionError:
            pass
        # get padding
        try:
            kwargs.setdefault(
                'padding', [eval(config.get(section, 'padding'))])
        except NoOptionError:
            pass
        # get list of metrics
        kwargs.setdefault(
            'metrics',
            [get_metric(f.strip('\n ')) for f in
                 config.get(section, 'metrics').split(',')])
        # get labels
        try:
            kwargs.setdefault(
                'labels',
                [f.strip('\n ') for f in
                     config.get(section, 'labels').split(',')])
        except NoOptionError:
            pass
        # get ETG params
        try:
            kwargs.setdefault(
                'channel', get_channel(config.get(section, 'event-channel')))
        except NoOptionError:
            pass
        else:
            kwargs.setdefault('etg', config.get(section, 'event-generator'))
            try:
                kwargs.setdefault('format', config.get(section, 'event-format'))
            except NoOptionError:
                pass
        # get flag combine
        if len(kwargs['flags']) > 1 and 'intersection' not in kwargs:
            try:
                combine = config.get(section, 'combine')
            except NoOptionError:
                kwargs['intersection'] = False
            else:
                if combine.lower() == 'intersection':
                    kwargs['intersection'] = True
                elif combine.lower() != 'union':
                    raise ValueError("Cannot parse flag combine operator %r" %
                                     combine)
                else:
                    kwargs['intersection'] = False
        # make tab and return
        new = super(ParentTab, cls).from_ini(config, section, **kwargs)
        return new

    def init_plots(self, plotdir=os.curdir):
        """Configure the default list of plots for this tab

        This method configures a veto-trigger glitchgram, histograms of
        before/after SNR and frequency/template duration,
        before and after glitchgrams, and a segment plot.

        This method is a mess, and should be re-written in a better way.
        """
        if self.intersection:
            label = 'Intersection'
        else:
            label = 'Union'

        etgstr = self.etg.replace('_', r'\\_')

        self.layout = [1,]
        before = get_channel(str(self.channel))
        for state in self.states:
            if self.channel:
                after = get_channel(veto_tag(before, self.metaflag,
                                             mode='after'))
                vetoed = get_channel(veto_tag(before, self.metaflag,
                                              mode='vetoed'))
                # -- configure trigger plots
                params = etg.get_etg_parameters(self.etg, IFO=before.ifo)
                glitchgramargs = {
                    'etg': self.etg,
                    'x': params['time'],
                    'y': params['frequency'],
                    'logy': params.get('frequency-log', True),
                    'ylabel': params.get('frequency-label',
                                         get_column_label(params['frequency'])),
                    'edgecolor': 'none',
                    'legend-scatterpoints': 1,
                    'legend-borderaxespad': 0,
                    'legend-bbox_to_anchor': (1.01, 1),
                    'legend-loc': 'upper left',
                }
                # plot before/after glitchgram
                self.plots.append(get_plot('triggers')(
                    [after, vetoed], self.start, self.end, state=state,
                    title='Impact of %s (%s)' % (
                        label_to_latex(self.name), etgstr),
                    outdir=plotdir, labels=['_', 'Vetoed'],
                    colors=['lightblue', 'red'], **glitchgramargs))

                # plot histograms
                statistics = ['snr']
                if params['det'] != params['snr']:
                    statistics.append('det')
                self.layout.append(len(statistics) + 1)
                for column in statistics + ['frequency']:
                    self.plots.append(get_plot('trigger-histogram')(
                        [before, after], self.start, self.end, state=state,
                        column=params[column], etg=self.etg, outdir=plotdir,
                        title='Impact of %s (%s)' % (
                            label_to_latex(self.name), etgstr),
                        labels=['Before', 'After'],
                        xlabel=params.get('%s-label' % column,
                                          get_column_label(params[column])),
                        color=['red', (0.2, 0.8, 0.2)],
                        logx=params.get('%s-log' % column, True),
                        logy=True,
                        histtype='stepfilled', alpha=0.6,
                        weights=1/float(abs(self.span)), bins=100,
                        ybound=1/float(abs(self.span)) * 0.5, **{
                            'legend-borderaxespad': 0,
                            'legend-bbox_to_anchor': (1.01, 1),
                            'legend-loc': 'upper left'}
                    ))

                # plot triggers before and after
                for stat in statistics:
                    column = params[stat]
                    glitchgramargs.update({
                        'color': column,
                        'clim': params.get('%s-limits' % stat, [3, 100]),
                        'logcolor': params.get('%s-log' % stat, True),
                        'colorlabel': params.get('%s-label' % stat,
                                                 get_column_label(column)),
                    })
                    self.plots.append(get_plot('triggers')(
                        [before], self.start, self.end, state=state,
                        outdir=plotdir, **glitchgramargs))
                    self.plots.append(get_plot('triggers')(
                        [after], self.start, self.end, state=state,
                        title='After %s (%s)' % (
                            label_to_latex(self.name), self.etg),
                        outdir=plotdir, **glitchgramargs))
                    self.layout.append(2)

            # -- configure segment plot
            segargs = {
                'state': state,
                'known': {'alpha': 0.1, 'facecolor': 'lightgray'},
                'color': 'red',
            }
            if len(self.flags) == 1:
                sp = get_plot('segments')(self.flags, self.start, self.end,
                                          outdir=plotdir, labels=self.labels,
                                          **segargs)
            else:
                sp = get_plot('segments')(
                    [self.metaflag] + self.flags, self.start, self.end,
                    labels=([self.intersection and 'Intersection' or 'Union'] +
                            self.labels), outdir=plotdir, **segargs)
            self.plots.append(sp)
            self.layout.append(1)

    def process_state(self, state, *args, **kwargs):
        config = kwargs.get('config', None)
        # first get all of the segments
        if self.segmentfile:
            get_segments(self.flags, state, config=config,
                         cache=self.segmentfile, return_=False)
            segs = get_segments(self.metaflag, state, padding=self.padding,
                                config=config, query=False)
            kwargs['segmentcache'] = Cache()
        else:
            segs = get_segments(self.metaflag, state, config=config,
                                segdb_error=kwargs.get('segdb_error', 'raise'),
                                padding=self.padding)
        # then get all of the triggers
        if self.channel:
            cache = kwargs.pop('trigcache', None)
            before = get_triggers(str(self.channel), self.etg, state,
                                  config=config, cache=cache,
                                  format=self.etgformat)
        else:
            before = None
        # then apply all of the metrics
        self.results[state] = evaluate_flag(
            segs, triggers=before, metrics=self.metrics, injections=None,
            minduration=self.minseglength, vetotag=str(state),
            channel=str(self.channel), etg=self.etg)[0]
        vprint("    Veto evaluation results:\n")
        for metric, val in self.results[state].iteritems():
            vprint('        %s: %s\n' % (metric, val))
        # then pass to super to make the plots
        kwargs['trigcache'] = Cache()
        return super(FlagTab, self).process_state(state, *args, **kwargs)

    def write_state_html(self, state):
        # write results table
        performance = [(str(m), '%.2f %s' % (r.value, r.unit),
                        m.description.split('\n')[0]) for
                       (m, r) in self.results[state].iteritems()]
        pre = html.markup.page()
        pre.div(class_='scaffold well')
        pre.strong('Flag performance summary')
        pre.add(str(html.table(['Metric', 'Result', 'Description'],
                               performance)))
        pre.div.close()
        pre.h2('Figures of Merit')
        # write configuration table
        post = html.markup.page()
        def add_config_entry(title, entry):
            post.tr()
            post.th(title)
            post.td(entry)
            post.tr.close()
        post.h2('Analysis configuration')
        post.div()
        post.table(class_='table table-condensed table-hover')
        add_config_entry('Flags', '<br>'.join(map(str, self.flags)))
        if len(self.flags) > 1 and self.intersection:
            add_config_entry('Flag combination', 'Intersection (logical AND)')
        elif len(self.flags) > 1:
            add_config_entry('Flag combination', 'Union (logical OR)')
        add_config_entry('Analysis start time', '%s (%s)' % (
            str(Time(float(self.start), format='gps', scale='utc').iso),
            self.start))
        add_config_entry('Analysis end time', '%s (%s)' % (
            str(Time(float(self.end), format='gps', scale='utc').iso),
            self.end))
        add_config_entry('Event trigger channel', str(self.channel))
        add_config_entry('Event trigger generator', str(self.etg))
        post.table.close()
        post.div.close()
        post.h2('Segment information')
        post.div(class_='panel-group', id="accordion")
        for i, flag in enumerate([self.metaflag] + self.flags):
            flag = get_segments(flag, state.active, query=False,
                                padding=self.padding).copy()
            post.div(class_='panel well panel-primary')
            post.div(class_='panel-heading')
            post.a(href='#flag%d' % i, **{'data-toggle': 'collapse',
                                          'data-parent': '#accordion'})
            if i == 0:
                post.h4(self.intersection and 'Intersection' or 'Union',
                        class_='panel-title')
            elif self.labels[i-1] != str(flag):
                post.h4('%s (%s)' % (flag.name, self.labels[i-1]),
                        class_='panel-title')
            else:
                post.h4(flag.name, class_='panel-title')
            post.a.close()
            post.div.close()
            post.div(id_='flag%d' % i, class_='panel-collapse collapse')
            post.div(class_='panel-body')
            # write segment summary
            post.p('This flag was defined and had a known state during '
                   'the following segments:')
            post.add(self.print_segments(flag.known))
            # write segment table
            post.p('This flag was active during the following segments:')
            post.add(self.print_segments(flag.active))

            post.div.close()
            post.div.close()
            post.div.close()
        post.div.close()

        # then write standard data tab
        return super(get_tab('default'), self).write_state_html(
            state, plots=True, pre=pre, post=post)

register_tab(FlagTab)
