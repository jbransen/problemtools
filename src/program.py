import glob
import os
import signal
#import resource
import logging
import re
import shutil
import tempfile
import shlex
import fnmatch
import platform
import subprocess
import threading
import traceback
from time import clock

def locate_program(candidatePaths):
    for p in candidatePaths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return Executable(p)
        if platform.system() == 'Windows':
            p = p + '.exe'
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return Executable(p)
    return None

def locate_checktestdata():
    defaultPaths = [os.path.join(os.path.dirname(__file__),
                                 'checktestdata/checktestdata'),
                    os.path.join(os.path.dirname(__file__),
                                 '../support/checktestdata/checktestdata'),
                    '/usr/lib/problemtools/bin/checktestdata']
    return locate_program(defaultPaths)

def locate_viva():
    defaultPaths = [os.path.join(os.path.dirname(__file__),
                                 'viva/viva.sh'),
                    os.path.join(os.path.dirname(__file__),
                                 '../support/viva/viva.sh'),
                    '/usr/lib/problemtools/bin/viva.sh']
    return locate_program(defaultPaths)


class ProgramError(Exception):
    pass

class ProgramWarning(Exception):
    pass

class Command(object):
    """
    Enables to run subprocess commands in a different thread with TIMEOUT option.

    Based on jcollado's solution:
    http://stackoverflow.com/questions/1191374/subprocess-with-timeout/4825933#4825933
    """
    command = None
    process = None
    status = None
    output, error = '', ''

    def __init__(self, command):
        if isinstance(command, basestring):
            command = shlex.split(command)
        self.command = command

    def run(self, timeout=None, **kwargs):
        """ Run a command then return: (status, output, error). """
        def target(**kwargs):
            try:
                start = clock()
                self.process = subprocess.Popen(self.command, **kwargs)
                self.output, self.error = self.process.communicate()
                self.status = self.process.returncode
                self.time = clock() - start
            except:
                self.time = clock() - start
                self.error = traceback.format_exc()
                self.status = -1
        # default stdout and stderr
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.PIPE
        # thread
        thread = threading.Thread(target=target, kwargs=kwargs)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.process.terminate()
            thread.join()
        return self.status, self.time

class Runnable:
    runtime = 0

    def run(self, infile='/dev/null', outfile='/dev/null', errfile='/dev/null', args=None, timelim=1000, logger=None):
        runcmd = self.get_runcmd()
        if runcmd == []:
            if logger != None:
                logger.error('Could not figure out how to run %s' % self)
            return (-1, 0.0)
        if args == None:
            args = []  # Damn you Python

        status, runtime = self._run_wait(runcmd + args, infile, outfile, errfile, timelim)

        self.runtime = max(self.runtime, runtime)

        return status, runtime

    def _run_wait(self, argv, infile="/dev/null", outfile="/dev/null", errfile="/dev/null", timelim=1000):
        logging.debug('run "%s < %s > %s 2> %s"', ' '.join(argv), infile, outfile, errfile)
        
        fin  = open(os.devnull if infile == '/dev/null' else infile, 'r')
        fout = open(os.devnull if outfile == '/dev/null' else outfile, 'w')
        ferr = open(os.devnull if errfile == '/dev/null' else errfile, 'w')
        
        command = Command(argv)
        return command.run(timeout=timelim, stdin=fin, stdout=fout, stderr=ferr)

    def _setfd(self, fd, filename, flag):
        tmpfd = os.open(filename, flag)
        os.dup2(tmpfd, fd)
        os.close(tmpfd)


class Executable(Runnable):
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)

    def __str__(self):
        return 'Executable(%s)' % (self.path)

    def compile(self):
        return True

    def get_runcmd(self):
        return [self.path]


class ValidationScript(Runnable):
    _TYPES = {'.ctd': {'run': locate_checktestdata(),
                       'input_src': 'stdin',
                       'compile_exit': 1,
                       'run_exit': 0},
              '.viva': {'run': locate_viva(), 
                        'input_src': 'arg',
                        'compile_exit': 0,
                        'run_exit': 0}}

    def __str__(self):
        return 'ValidationScript(%s)' % (self.path)

    def __init__(self, path):
        ext = os.path.splitext(path)[1]
        if not os.path.isfile(path) or ext not in ValidationScript._TYPES.keys():
            raise ProgramWarning('Not a recognized validation script')
        self.path = path
        self.name = path
        self.runcmd = None
        self.type = ValidationScript._TYPES[ext]
        if self.type['run'] is not None:
            self.runcmd = self.type['run'].get_runcmd() + [path]

    _compile_result = None
    def compile(self):
        if self._compile_result is None:
            self._compile_result = False
            (status, runtime) = self.run(switch_exitcodes=False)
            self._compile_result = status == self.type['compile_exit']
        return self._compile_result

    def run(self, infile='/dev/null', outfile='/dev/null', errfile='/dev/null', args=None, timelim=1000, logger=None, switch_exitcodes=True):
        if self.runcmd is None:
            raise ProgramError('Could not locate runner for validation script %s' % self.path)
        if self.type['input_src'] == 'arg' and infile != '/dev/null':
            args = [infile]
        (status, runtime) = Runnable.run(self, infile, outfile, errfile, args, timelim, logger)
        # This is ugly, switches the accept exit status and our accept exit status 42.
        if switch_exitcodes:
            if status == self.type['run_exit']:
                status = 42<<8
            elif status == 42:
                status = self.type['run_exit'] << 8
        return (status, runtime)
    
    def get_runcmd(self):
        return self.runcmd


class Program(Runnable):
    # TODO: make language settings more configurable
    _LANGNAME = {
        'c': 'C',
        'cpp': 'C++',
        'csharp': 'C#',
        'go': 'Go',
        'haskell': 'Haskell',
        'java': 'Java',
        'objectivec': 'Objective-C',
        'prolog': 'Prolog',
        'python2': 'Python 2',
        'python3': 'Python 3',
        'ruby': 'Ruby',
        'javascript': 'JavaScript',
        'php': 'PHP'
    }
    _GLOBS = {'c': '*.c',
              'cpp': '*.cc *.C *.cpp *.cxx *.c++',
              'java': '*.java',
              'csharp': '*.cs',
              'python2': '*.py',
              'python3': '*.py',
              'ruby': '*.rb',
              'go': '*.go',
              'haskell': '*.hs',
              'objectivec': '*.m',
              'prolog': '*.pl',
              'javascript': '*.js',
              'php': '*.php',
          }
    _SHEBANGS = {'python2': r"^#!.*python2\b",
                 'python3': r"^#!.*python3\b"}
    _SHEBANG_DEFAULT = ['python2']
    _COMPILE = {
        'c': 'gcc -g -O2 -static -std=gnu99 -o "%(exe)s" %(src)s -lm' if platform.system() != 'Darwin' else 'gcc -g -O2 -std=gnu99 -o "%(exe)s" %(src)s -lm',
        'cpp': 'g++ -g -O2 -static -std=gnu++11 -o "%(exe)s" %(src)s' if platform.system() != 'Darwin' else 'g++ -g -O2 -std=gnu++11 -o "%(exe)s" %(src)s',
        'java': 'javac -d %(path)s %(src)s',
        'prolog': 'swipl -O -q -g main -t halt -o "%(exe)s" -c %(src)s',
        'csharp': 'csc /optimize+ /out:%(exe)s.exe %(src)s',
        'go': 'gccgo -g -static-libgcc -o "%(exe)s" %(src)s',
        'haskell': 'ghc -O2 -ferror-spans -threaded -rtsopts -o "%(exe)s" %(src)s',
        'dir': 'cd "%(path)s" && ./build',
        }
    _RUN = {
        'c': ['%(exe)s'],
        'cpp': ['%(exe)s'],
        'java': ['java','-Xmx2048m','-Xss64m', '-cp', '%(path)s', '%(mainclass)s'],
        'prolog': ['%(exe)s'],
        'python2': ['python','%(mainfile)s'],
        'python3': ['python3','%(mainfile)s'],
        'ruby': ['ruby','%(mainfile)s'],
        'csharp': ['%(exe)s.exe'],
        'go': ['%(exe)s'],
        'haskell': ['%(exe)s'],
        'dir': ['%(path)s/run'],
        'javascript': ['js24', '%(mainfile)s'],
        'php': ['php','-n','%(mainfile)s'],
        }
    _RUN_PATH_VARS = ['path', 'mainfile', 'exe']

    def check_shebang(self, file):
        shebang_line = open(file, 'r').readline()
        for (lang,shebang_pattern) in Program._SHEBANGS.iteritems():
            if re.search(shebang_pattern, shebang_line):
                return lang
        return None

    def list_files(self, lang):
        if lang in ['dir']:
            return None

        globs = Program._GLOBS[lang].split()
        result = []
        for (path,dirs,files) in os.walk(self.path):
            for f in files:
                fullpath = os.path.join(self.path, path, f)
                for g in globs:
                    if fnmatch.fnmatch(fullpath, g):
                        if lang in Program._SHEBANGS.keys():
                            sheblang = self.check_shebang(fullpath)
                            if ((sheblang is None and lang not in Program._SHEBANG_DEFAULT) or
                                (sheblang is not None and sheblang != lang)):
                                continue
                        result.append(fullpath)
                        break
        return result

    def guess_language(self):
        files = [os.path.join(self.path, f) for f in os.listdir(self.path)]
        executables = [os.path.basename(f) for f in files if os.access(f, os.X_OK)]
        has_build = 'build' in executables
        has_run = 'run' in executables
        if has_build and has_run:
            return 'dir'
        elif has_build:
            raise ProgramWarning("Has build script but no run script; I'm confused and won't use this")
        elif has_run:
            raise ProgramWarning("Has run script but no build script; I'm confused and won't use this")

        possible_langs = []
        for lang in Program._GLOBS:
            if len(self.list_files(lang)) > 0:
                possible_langs.append(lang)

        if len(possible_langs) == 1:
            return possible_langs[0]

        if len(possible_langs) > 1:
            raise ProgramError('Could not uniquely determine language.  Candidates are: %s' % (', '.join(possible_langs)))

        raise ProgramWarning('Could not guess any language.')
        
            
    def add_files(self, srcdir):
        for f in os.listdir(srcdir):
            src = os.path.join(srcdir, f)
            dest = os.path.join(self.path, f)
            if os.path.isdir(src):
                shutil.copytree(src, dest)
            else:
                shutil.copy(src, dest)

    def __init__(self, path, workdir, includedir=None):
        if path[-1] == '/':
            path = path[:-1]
        self.name = os.path.basename(path)
        self.path = os.path.join(workdir, self.name)
        if os.path.exists(self.path):
            self.path = tempfile.mkdtemp(prefix='%s-' % self.name, dir=workdir)
        else:
            os.makedirs(self.path)

        if os.path.isdir(path):
            self.add_files(path)
        else:
            shutil.copy(path, self.path)

        self.lang = self.guess_language()

        if includedir is not None:
            includedir = os.path.join(includedir, self.lang)
            if os.path.isdir(includedir):
                self.add_files(includedir)

        self.srclist = self.list_files(self.lang)
        if self.srclist is not None:
            self.src = ' '.join(self.srclist)
            mainfiles = [x for x in self.srclist if re.match('^[Mm]ain\.', os.path.basename(x))]
            if len(mainfiles) > 1:
                raise ProgramError('Multiple possible main-files: %s' % ', '.join(mainfiles))
            self.mainfile = mainfiles[0] if len(mainfiles) == 1 else self.srclist[0]
            self.mainclass = os.path.splitext(os.path.basename(self.mainfile))[0]
        self.exe = os.path.join(self.path, 'run')


    _compile_result = None

    def compile(self, logger=None):
        if self._compile_result is not None:
            return self._compile_result

        if self.lang not in Program._COMPILE:
            self._compiler_result = True
            return True

        compiler = (Program._COMPILE[self.lang]) % self.__dict__
        logging.debug('compile: %s', compiler)
        
        out = open(os.devnull, 'wb')
        status = subprocess.call(compiler, stdout=out, stderr=out)

        if status != 0:
            if logger is not None:
                logger.error('Compiler failed (status %d) when compiling %s\n        Command used: %s' % (status, self.name, compiler))
            self._compile_result = False
            return False

        self._compile_result = True
        return True


    runtime = 0


    def get_runcmd(self, cwd=None):
        self.compile()
        vals = self.__dict__
        if cwd is not None:
            vals = vals.copy()
            for key in Program._RUN_PATH_VARS:
                if key in vals:
                    vals[key] = os.path.relpath(vals[key], cwd)
        return map(lambda x: x % vals, Program._RUN[self.lang])


    def __str__(self):
        return 'Program(%s)' % (self.name)

