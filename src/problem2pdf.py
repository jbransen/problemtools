#! /usr/bin/env python2
# -*- coding: utf-8 -*-
import re
import os.path
import subprocess
import sys
import string
from string import Template
from optparse import OptionParser
import logging
import template
from shutil import move


def convert(problem, options=None):
    if options == None:
        options = ConvertOptions()

    problem = os.path.realpath(problem)
    problembase = os.path.splitext(os.path.basename(problem))[0]
    destfile = Template(options.destfile).safe_substitute(problem=problembase)

    texfile = problem
    # Set up template if necessary
    templ = None
    if os.path.isdir(problem):
        templ = template.Template(problem, language=options.language,
                                  title=options.title)
        texfile = templ.get_file_name()

    origcwd = os.getcwd()

    os.chdir(os.path.dirname(texfile))
    out = open(os.devnull, 'wb') if options.quiet else None
    params = ['-interaction=nonstopmode']
    if options.nopdf:
        params.append('-draftmode')

    status = subprocess.call(['pdflatex'] + params + [texfile], stdout=out)
    if status == 0:
        status = subprocess.call(['pdflatex'] + params + [texfile], stdout=out)

    os.chdir(origcwd)

    if not options.nopdf:
        move(os.path.splitext(texfile)[0] + '.pdf', destfile)

    if templ != None:
        templ.cleanup()

    return status == 0


class ConvertOptions:
    available = [
        ['destfile', 'store', '-o', '--output',
         "output file name."],
        ['quiet', 'store_true', '-q', '--quiet',
         "quiet."],
        ['title', 'store', '-T', '--title',
         'set title (only used when there is no pre-existing template and -h not set).'],
        ['language', 'store', '-l', '--language',
         'choose alternate language (2-letter code).'],
        ['nopdf', 'store_true', '-n', '--no-pdf',
         'run pdflatex in -draftmode'],
        ]

    def __init__(self):
        self.destfile = "${problem}.pdf"
        self.title = "Problem Name"
        self.quiet = False
        self.language = ""
        self.nopdf = False


if __name__ == '__main__':
    options = ConvertOptions()
    optparse = OptionParser(usage="usage: %prog [options] problem")
    for (dest, action, short, long, help) in ConvertOptions.available:
        if (action == 'store'):
            help += ' default: "%s"' % options.__dict__[dest]
        optparse.add_option(short, long, dest=dest, help=help, action=action)

    (options, args) = optparse.parse_args(values=options)

    if len(args) != 1:
        optparse.print_help()
        sys.exit(1)

    texfile = args[0]
    convert(texfile, options)
