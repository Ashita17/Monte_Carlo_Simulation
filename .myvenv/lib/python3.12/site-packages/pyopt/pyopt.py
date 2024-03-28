"""
pyopt version 0.84

A module for command-line options with a pythonic, decorator-centric syntax.

The following example auto-generates help with docstrings, type casting for
arguments and enforcing argument count:

    import pyopt

    expose = pyopt.Exposer()

    @expose.args
    def regular_function(arg1:str, arg2:int):
        '''Your help - the docstring'''
        # bla, etc, foobar spam...
        print(repr(arg1), repr(arg2))

    if __name__ == "__main__":
        expose.run()

There are 3 modes of operation:
    1. expose.args - A decorator for positional arguments.
    2. expose.kwargs - A decorator for keyword arguments.
    3. expose.mixed - A decorator for keyword and positional arguments.

Currently known compromises that are open to discussion, e-mail me:
    1. This module was specifically designed with python 3 in mind, certain features
        can be converted to python 2.x, but the awesome ones can't.
    2. Keyword command-line functions require every argument to start with a
        different letter to avoid collisions.
    3. Annotations aren't mandatory, I don't know if this is the right way to go,
        it's an explicity vs convenience issue.
    4. Booleans can't default to True. I couldn't think of a use case for this
        so tell me if you did.

License: whatever, I don't mind. Google Code made me choose so I went with
the "New BSD". If somebody has a better idea, e-mail, comment or whatnot.
Hearing from whoever uses this code would be nice, but you really shouldn't
feel obliged.

Contact me at: ubershmekel at gmail
"""


import sys
from os.path import basename
import getopt
import inspect
import re
import types

class PyoptError(Exception): pass
class PrintHelp(PyoptError): pass
class NotEnoughArgs(PyoptError): pass

HELP_SET = set(["-h", "--help", "/?", "?", "-?"])

# DBG
#import pdb, sys, traceback
#def info(type, value, tb):
#    traceback.print_exception(type, value, tb)
#    pdb.pm()
#sys.excepthook = info
# DBG



def _indent(string, tab_count):
    lines = string.splitlines()
    lines = [("\t" * tab_count) + ln.strip() for ln in lines]
    return '\n'.join(lines)


def _bool_cast(name, value):
    return True


_DEFAULT_SPECIAL_CASTS = {
    bool: _bool_cast,
    }



class _FunctionWrapper:
    def __init__(self, function, default_cast=str):
        """
        Gives all the needed information about a function and puts it in
        attributes on the function. ie:
        function.required == [list of required arguments]
        
        NOTE: set() calculations weren't used in order to preserve order
            for positional arguments.
        """
        
        args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations = _getfunctionspec(function)
        
        
        arg_names = args
        defaults_count = len(defaults)
        not_default_count = len(arg_names) - defaults_count
        not_defaulted = arg_names[:not_default_count]
        defaulted_args = arg_names[not_default_count:]
        defaults_dict = dict(zip(defaulted_args, defaults))
        
        # get all the casts from the annotations, default to default_cast (probably str)
        #casts = {name: annotations.get(name, default_cast) for name in arg_names}
        casts = {}
        for i, name in enumerate(arg_names):
            if name in annotations:
                casts[name] = annotations[name]
            elif name in defaults_dict:
                casts[name] = type(defaults_dict[name])
            else:
                casts[name] = default_cast
        booleans = [arg for arg in arg_names if casts[arg] is bool]
        required = [arg for arg in not_defaulted if arg not in booleans]
        
        # pass around the information
        self.function = function
        self.arg_names = arg_names
        self.name = function.__name__
        self.required = required
        self.optional = set(arg_names) - set(required)
        self.booleans = booleans
        self.defaults_count = defaults_count
        self.needed_args = len(self.arg_names) - self.defaults_count
        
        self.casts = casts
        self.special_casts = dict(_DEFAULT_SPECIAL_CASTS)
        
    
    def __call__(self, *args, **kwargs):
        return self.function(*args, **kwargs)
    
    def cast_parameter(self, name, value):
        try:
            type_to_cast = self.casts[name]
            if type_to_cast in self.special_casts:
                cast_func = self.special_casts[type_to_cast]
                return cast_func(name, value)
            parsed_arg = type_to_cast(value)
            return parsed_arg
        except Exception as e:
            raise PyoptError("Failed parsing '%s', %s." % (name, e))
    
    def get_doc(self):
        if self.function.__doc__ is None:
            return ""
        else:
            # strip for the docstring guys that don't want text on the same line with '''
            return _indent(self.function.__doc__.strip(), 2)
    
    def get_usage(self):
        return "\t%s %s\n%s" % (self.name, self.parameters_repr(), self.get_doc())
    
    def parameters_repr(self):
        """
        This function should be implemented by subclasses to return a string
        that represents the parameters with which to call the function
        from a command line or shell.
        """
        raise NotImplementedError
        
    def parse(self, raw_args=[]):
        """
        raw_args - a list of arguments and options as would be given by sys.argv
        
        This function should be implemented by subclasses and must return
        a list and a dictionary, args and kwargs, that way it's easy to call
        the function.
        
        In case not enough/too many args were given raise a PyoptError.
        """
        raise NotImplementedError

    def docstring_usage(self):
        summary, docs_dict = _parse_docstring(self.function)
        usage_lines = [summary]
        short_to_name = self._shortcuts()
        for name, explanation in docs_dict.items():
            short = name[0]
            if short_to_name[short] == name:
                usage_lines.append('\t-%s --%s - %s' % (name[0], name, explanation))
            else:
                usage_lines.append('\t--%s - %s' % (name, explanation))
        return '\n'.join(usage_lines)

class _ArgsFunction(_FunctionWrapper):
    def parameters_repr(self):
        req_str = ["%s" % arg for arg in self.required]
        opt_str = ["[%s]" % arg for arg in self.optional]
        
        return " ".join(req_str + opt_str)
    
    def docstring_usage(self):
        summary, docs_dict = _parse_docstring(self.function)
        usage_lines = [summary]
        for name, explanation in docs_dict.items():
            usage_lines.append('\t%s - %s' % (name, explanation))
        return '\n'.join(usage_lines)
    
    def parse(self, raw_args=[]):
        # NOTE: not len(required) because no need to mix with kw_parse boolean logic.
        
        if len(raw_args) < self.needed_args:
            raise NotEnoughArgs("%d arguments required, got only %d." % (self.needed_args, len(raw_args)))
        if len(raw_args) > len(self.arg_names):
            raise PyoptError("Got %d arguments and expected at most %d." % (len(raw_args), len(self.arg_names)))
        
        args_to_call_with = []
        for arg, arg_name in zip(raw_args, self.arg_names):
            parsed_arg = self.cast_parameter(arg_name, arg)
            args_to_call_with.append(parsed_arg)
        
        return args_to_call_with, {}

class _MixedFunction(_FunctionWrapper):
    def parameters_repr(self):
        # self.arg_names is the authorative order
        # todo: fix this
        req_str = ["-%s %s" % (arg[0], arg) for arg in self.required]
        opt_str = ["[-%s %s]" % (arg[0], arg) for arg in self.optional if arg not in self.booleans]
        bools_str = ["[-%s]" % arg[0] for arg in self.booleans]
        return " ".join(req_str + opt_str + bools_str)


    def _shortcuts(self):
        return dict([(name[0], name) for name in self.arg_names])

    def parse(self, raw_args=[]):
        short_to_name = self._shortcuts()
        
        shorts_str = ''
        shorts_str += ''.join([[name][0] for name in self.booleans])
        shorts_str += ''.join(["%s:" % name[0] for name in self.required])
        long_opts = []
        long_opts += [name for name in self.booleans]
        long_opts += ["%s=" % name for name in self.required]
        
        optlist, uncasted_args_list = getopt.getopt(raw_args, shorts_str, long_opts)

        pos_args = list(self.arg_names)
        kwargs_dict = {}
        for opt, val in optlist:
            if opt.startswith('--'):
                name = opt[2:]
            elif opt.startswith('-'):
                short = opt[1]
                name = short_to_name[short]
            
            kwargs_dict[name] = self.cast_parameter(name, val)
            # remove all the arguments which came from switches, the remainder
            # will be used for positional arguments 
            pos_args.remove(name)
        
        args_list = []
        args_given = []
        for name, val in zip(pos_args, uncasted_args_list):
            args_list.append(self.cast_parameter(name, val))
            args_given.append(name)
        
        # make sure all non-boolean, non-defaulted args were given
        not_key_given = [arg for arg in self.required if arg not in kwargs_dict]
        not_given = [arg for arg in not_key_given if arg not in args_given]
        
        if len(not_given) > 0:
            raise NotEnoughArgs("The following options are required: %s." % ', '.join(not_given))
            
        return args_list, kwargs_dict

class _KwargsFunction(_FunctionWrapper):
    def parameters_repr(self):
        req_str = ["-%s %s" % (arg[0], arg) for arg in self.required]
        opt_str = ["[-%s %s]" % (arg[0], arg) for arg in self.optional if arg not in self.booleans]
        bools_str = ["[-%s]" % arg[0] for arg in self.booleans]
        
        return " ".join(req_str + opt_str + bools_str)

    def _shortcuts(self):
        return {name[0]: name for name in self.arg_names}
    
    def parse(self, raw_args=[]):
        short_to_name = self._shortcuts()
        
        # where all the parsed arguments will be stored {name:value}
        args_dict = {}
        
        # default all bools to false
        for name in self.booleans:
            args_dict[name] = False
        
        
        # parse the rest
        i = 0
        while i < len(raw_args):
            argument = raw_args[i]
            # find out the name of the argument
            if argument.startswith("--"):
                name = argument[2:]
            elif argument.startswith("-"):
                if len(argument) == 2:
                    name = short_to_name[argument[1]]
                elif len(argument) > 2:
                    # many boolean options
                    for short in argument[1:]:
                        name = short_to_name[short]
                        if name not in self.booleans:
                            raise PyoptError("Illegal option '%s' given as boolean." % short)
                        args_dict[name] = True
                    i += 1
                    continue
            else:
                raise PyoptError("Options must start with '-' or '--'.")
            
            if name not in self.arg_names:
                raise PyoptError("Illegal option '%s' given." % name)
            
            val_type = self.casts[name]
            if val_type == bool:
                parsed_val = True
            else:
                # if not a bool then the next arg is the value of this option
                val = raw_args[i + 1]
                parsed_val = self.cast_parameter(name, val)
                i += 1
            
            args_dict[name] = parsed_val
            
            i += 1
        
        # make sure all non-boolean, non-defaulted args were given
        not_given = [arg for arg in self.required if arg not in args_dict]
        
        if len(not_given) > 0:
            raise NotEnoughArgs("The following options are required: %s." % ', '.join(not_given))
        
        return [], args_dict

class Exposer:
    def __init__(self, kw_funcs_list=[], pos_funcs_list=[], mixed_funcs_list=[], default_cast=str):
        """
        Instead of decorators, you can pass functions to expose as a list.
        """
        self.functions_dict = {}
        #py3k - self.printer = print
        self.printer = __builtins__.get('print')
        
        self.default_cast = default_cast
        
        for function in kw_funcs_list:
            self.kwargs(function)
        for function in pos_funcs_list:
            self.args(function)
        for function in mixed_funcs_list:
            self.mixed(function)
        
    
    def args(self, function):
        """
        A decorator that exposes the given function as a command-line function.
        Arguments will be passed by their order, without "switches" or options.
        """
        self.functions_dict[function.__name__] = _ArgsFunction(function, default_cast=self.default_cast)
        return function
    
    def kwargs(self, function):
        """
        A decorator that gives the getopt/optparse functionality and exposes
        the given function. Some notes:
        
        1. All arguments to the function are passed using hyphens and can be shortened.
        2. Arguments with default values will be optional arguments.
        3. Arguments marked as bool don't take a parameter (just "-d" as opposed to "-d something")
        """
        self.functions_dict[function.__name__] = _KwargsFunction(function, default_cast=self.default_cast)
        return function
    
    def mixed(self, function):
        """
        A decorator that gives the getopt/optparse functionality and exposes
        the given function. Some notes:
        
        1. The first arguments to the function are passed using ie: -f or --fullname.
        2. Arguments with default values will be optional arguments.
        3. Arguments marked as bool don't take a parameter (just "-d" as opposed to "-d something")
        4. The first argument without a hyphen is the first positional argument.
            from then on, no more options, just positional args.
        """
        self.functions_dict[function.__name__] =  _MixedFunction(function, default_cast=self.default_cast)
        return function
    
    def _setup(self, cmd_args):
        if isinstance(cmd_args, str):
            cmd_args = cmd_args.split()
        self.cmd_args = cmd_args
        self.script_name = basename(cmd_args[0])
        total_funcs = len(self.functions_dict)
        if total_funcs == 0:
            raise NotImplementedError("No functions were decorated for command-line usage.")
        
        if total_funcs == 1:
            self.is_single = True
            self.raw_args = cmd_args[1:]
            self.func = next(iter(self.functions_dict.values()))
            if (len(cmd_args) > 1) and (cmd_args[1] in HELP_SET):
                raise PrintHelp(self._complete_usage())
        else:
            # Multiple functions decorated :)
            # the first arg must be either the function name or help.
            # Find out which function this is.
            self.is_single = False
            self.raw_args = cmd_args[2:]
            
            if len(cmd_args) < 2:
                # not single so must be given a function name.
                raise PrintHelp(self._complete_usage())
            
            if cmd_args[1] in HELP_SET:
                raise PrintHelp(self._give_help())
            
            if cmd_args[1] in self.functions_dict:
                func_name = cmd_args[1]
                self.func = self.functions_dict[func_name]
            else:
                raise PyoptError("Unkown function '%s'." % cmd_args[1])
    
    def parse_args(self, cmd_args):
        self._setup(cmd_args)
        
        try:
            args, kwargs = self.func.parse(self.raw_args)
        except NotEnoughArgs as e:
            if len(self.raw_args) == 0:
                # no arguments given at all must mean noob trying to get info.
                raise PrintHelp(self._func_usage())
            else:
                raise
        
        return self.func.function, args, kwargs
        
    def run(self, cmd_args=sys.argv):
        try:
            func, args, kwargs = self.parse_args(cmd_args)
            return func(*args, **kwargs)
        except PrintHelp as e:
            self.printer(e)
        except ValueError as e:
            self.printer("%s. Run with ? or -h for more help." % e)
        except PyoptError as e:
            self.printer(e, "Run with ? or -h for more help.")
    
    def _single_usage(self):
        func = self.func
        args_repr = func.parameters_repr()
        usage = "Usage: %s %s" % (self.script_name, args_repr)
        
        usage += '\n' + func.docstring_usage()
        #if func.function.__doc__ is not None:
        #    # strip for the docstring guys that don't want text on the same line with '''
        #    usage += "\n" + _indent(func.function.__doc__.strip(), 1)
        return usage
    
    def _func_usage(self):
        if self.is_single:
            return self._single_usage()
        else:
            return(self.func.get_usage())
    
    def _complete_usage(self):
        if self.is_single:
            return self._single_usage()
        
        usage_lines = []
        usage_lines.append("Usage: %s [function_name] [args]" % self.script_name)
        usage_lines.append("Available functions are:")
        for func in self.functions_dict.values():
            usage_lines.append(func.get_usage())
        return '\n'.join(usage_lines)
    
    
    def _give_help(self):
        try:
            # give help to a specific func, if an index error occurs, give complete usage.
            func_name = self.cmd_args[2]
            # in case the function isn't found, a KeyError is thrown so
            # the complete usage will be printed.
            self.func = self.functions_dict[func_name]
            return(self.func.get_usage())
        except (IndexError, KeyError) as e:
            # print usage for this script
            return self._complete_usage()  

def _getfunctionspec(function):
    if hasattr(function, '__annotations__'):
        # python 3 only
        arg_names_list, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations = inspect.getfullargspec(function)
    else:
        arg_names_list, varargs, varkw, defaults = inspect.getargspec(function)
        kwonlyargs, kwonlydefaults, annotations = [], {}, {}
    
    # defaults should have been an empty list, come on Guido...
    if defaults is None:
        defaults = []

    # A fix for class-methods and instance-methods is to remove the first
    # argument name (which is self or cls).
    # In case of (*args, **kwargs) we don't intervene.
    if isinstance(function, types.MethodType) and len(arg_names) > 0:
        arg_names.pop(0)
            
    return arg_names_list, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations

def _parse_docstring(function):
    r"""
    Parses a function's docstring for parameter documentation like this:
        function - the function whose docstring is parsed.
    
    returned is the tuple (summary, docs_dict)
        summary - the text before the first line of parameter documentation.
        docs_dict - keys are parameter names and the values are the parameter's
            documentation string.
    
    NOTE: The parsing algorithm just looks for lines that start with a parameter
        name immediately followed by any amount of whitespace, hyphens or
        colons. What follows the colon/hyphen/whitespace is the help.
    WARNING: _parse_docstring only works with one line of documentation per
        parameter so if you want to divide it to multiple lines use the \
        character.
    """
    arg_names_list, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations = _getfunctionspec(function)
    docs = function.__doc__
    if docs is None:
        docs = ''
    
    lines = docs.splitlines()
    
    # find parameter documentation:
    names = '|'.join(arg_names_list)
    var_doc_re = re.compile(r'(%s)[ \t-:]*(.*)' % names)
    docs_dict = {}
    
    # first line where a param shows up. Initialized to an unreachable number.
    first_line = len(docs)
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        match = var_doc_re.match(stripped)
        if match:
            if i < first_line:
                first_line = i
            name, doc = match.groups()
            docs_dict[name] = doc.strip()
    
    if first_line < len(docs):
        summary_lines = lines[:first_line]
        summary = '\n'.join(summary_lines).strip()
    else:
        summary = ''
    
    return summary, docs_dict


