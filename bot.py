#!/usr/bin/env python
"""
bot.py - Phenny IRC Bot
Copyright 2008, Sean B. Palmer, inamidst.com
Licensed under the Eiffel Forum License 2.

http://inamidst.com/phenny/
"""

import sys, os, re, imp, time, traceback
from tools import startdaemon
import irc

home = os.getcwd()

def decode(bytes): 
    try: text = bytes.decode('utf-8')
    except UnicodeDecodeError: 
        try: 
            text = bytes.decode('iso-8859-1')
        except UnicodeDecodeError: 
            text = bytes.decode('cp1252')
    return text

class PhennyWrapper(object): 
    def __init__(self, phenny, origin, text, match): 
        self.bot = phenny
        self.origin = origin
        self.text = text
        self.match = match
        self.sender = origin.sender or text
    
    def reply(self, msg):
        self.msg(self.sender, self.origin.nick + ': ' + msg)
    
    def say(self, msg):
        self.msg(self.sender, msg)
    
    def msg(self, recipient, text):
        self.bot.msg(recipient, text)
    
    def __getattr__(self, attr): 
        # This isn't used by super() >.<
        return getattr(self.bot, attr)

class CommandInput(unicode): 
    def __new__(cls, bot, text, origin, bytes, match, event, args): 
        self = unicode.__new__(cls, text)
        self.sender = origin.sender
        self.nick = origin.nick
        self.origin = origin
        self.event = event
        self.bytes = bytes
        self.match = match
        self.group = match.group
        self.groups = match.groups
        self.args = args
        self.admin = origin.nick in bot.config.admins
        self.owner = origin.nick == bot.config.owner
        return self
    
    def __repr__(self):
        perms = []
        if self.admin:
            perms.append('admin')
        if self.owner:
            perms.append('owner')
        perms = ' '.join(perms)
        if perms: 
            perms = ' '+perms
        
        t = type(self)
        clsname = "%s.%s" % (t.__module__, t.__name__)
        
        props = vars(self).copy()
        del props['admin']
        del props['owner']
        del props['match']
        del props['group']
        del props['bytes']
        del props['origin']
        props['groups'] = self.groups()
        pstr = ' '.join("%s=%r" % item for item in sorted(props.items(), key=lambda i: i[0]))
        
        return "<%s %s %s %s>" % \
            (clsname, super(CommandInput, self).__repr__(), pstr, perms)

class Phenny(irc.Bot):
    def __init__(self, config): 
       args = (config.nick, config.name, config.channels, config.password)
       irc.Bot.__init__(self, *args)
       self.config = config
       self.doc = {}
       self.stats = {}
       self.activity = {}
       self.DataStore = __import__('storebackends.'+getattr(config, 'datastore', 'jsonfile'), fromlist=['DataStore'], ).DataStore
       
       # Used to track extensions
       self.CommandInput = CommandInput
       self.PhennyWrapper = PhennyWrapper
       # Must be last
       self.setup()
    
#######################
#   INITIALIZATION    #
#         AND         #
# MODULE REGISTRATION #
#######################
    
    def setup(self): 
        self.variables = {}
        
        filenames = []
        if not hasattr(self.config, 'enable'): 
            for fn in os.listdir(os.path.join(home, 'modules')): 
                if fn.endswith('.py') and not fn.startswith('_'): 
                    filenames.append(os.path.join(home, 'modules', fn))
        else: 
            for fn in self.config.enable: 
                filenames.append(os.path.join(home, 'modules', fn + '.py'))
        
        if hasattr(self.config, 'extra'): 
            for fn in self.config.extra: 
                if os.path.isfile(fn): 
                    filenames.append(fn)
                elif os.path.isdir(fn): 
                    for n in os.listdir(fn): 
                        if n.endswith('.py') and not n.startswith('_'): 
                            filenames.append(os.path.join(fn, n))
        
        self.modules = []
        excluded_modules = getattr(self.config, 'exclude', [])
        for filename in filenames: 
            name = os.path.splitext(os.path.basename(filename))[0]
            if name in excluded_modules: continue
            try: 
                module = imp.load_source(name, filename) #XXX: This is an obsolete function
            except KeyboardInterrupt:
                raise
            except Exception, e:
                traceback.print_exc()
                print >> sys.stderr, "Error loading %s: %s (in bot.py)" % (name, e)
            else:
                try:
                    #STORAGE: Initialize the module store
                    if hasattr(module, 'storage'):
                        module.storage = self.DataStore(self, module, module.storage)
                    if hasattr(module, 'setup'): 
                        module.setup(self)
                except KeyboardInterrupt:
                    raise
                except:
                    #TODO: Report exception
                    raise
                else:
                    self.register(vars(module))
                    self.modules.append(module)
        
        if self.modules: 
            print >> sys.stderr, 'Registered modules:', ', '.join(m.__name__ for m in self.modules)
        else: 
            print >> sys.stderr, "Warning: Couldn't find any modules"
        
        self.bind_commands()
    
    def register(self, variables): 
        # This is used by reload.py, hence it being methodised
        for name, obj in variables.iteritems(): 
            if hasattr(obj, 'commands') or hasattr(obj, 'rule'): 
                self.variables[name] = obj
    
    def subnick(self, pattern): 
        # These replacements have significant order
        pattern = pattern.replace('$nickname', self.nick)
        return pattern.replace('$nick', r'%s[,:] +' % self.nick)
        
    def bind_func(self, priority, regexp, func): 
#         print priority, regexp.pattern.encode('utf-8'), func
        # register documentation
        if not hasattr(func, 'name'): 
            func.name = func.__name__
        if func.__doc__: 
            if hasattr(func, 'example'): 
                example = func.example
                example = example.replace('$nickname', self.nick)
            else: 
                example = None
            self.doc[func.name] = (func.__doc__, example)
        self.commands[priority].setdefault(regexp, []).append(func)
    
    COMMAND_DEFAULTS = {
        'priority' : 'medium',
        'thread' : True,
        'event' : 'PRIVMSG',
        }
    def bind_commands(self): 
        self.commands = {'high': {}, 'medium': {}, 'low': {}}
        
        for name, func in self.variables.iteritems(): 
#            print name, func
            for attr, default in self.COMMAND_DEFAULTS.items():
                if not hasattr(func, attr): 
                    setattr(func, attr, default)
            
            func.event = func.event.upper()
            
            if hasattr(func, 'rule'): 
                if isinstance(func.rule, str): 
                    pattern = self.subnick(func.rule)
                    regexp = re.compile(pattern)
                    self.bind_func(func.priority, regexp, func)
                
                elif isinstance(func.rule, tuple): 
                    # 1) e.g. ('$nick', '(.*)')
                    if len(func.rule) == 2 and isinstance(func.rule[0], str): 
                        prefix, pattern = func.rule
                        prefix = self.subnick(prefix)
                        regexp = re.compile(prefix + pattern)
                        self.bind_func(func.priority, regexp, func)
                    
                    # 2) e.g. (['p', 'q'], '(.*)')
                    elif len(func.rule) == 2 and isinstance(func.rule[0], list): 
                        prefix = self.config.prefix
                        commands, pattern = func.rule
                        for command in commands: 
                            command = r'(%s)\b(?: +(?:%s))?' % (command, pattern)
                            regexp = re.compile(prefix + command)
                            self.bind_func(func.priority, regexp, func)
                        
                    # 3) e.g. ('$nick', ['p', 'q'], '(.*)')
                    elif len(func.rule) == 3: 
                        prefix, commands, pattern = func.rule
                        prefix = self.subnick(prefix)
                        for command in commands: 
                            command = r'(%s) +' % command
                            regexp = re.compile(prefix + command + pattern)
                            self.bind_func(func.priority, regexp, func)
            
            if hasattr(func, 'commands'): 
                for command in func.commands: 
                    template = r'^%s(%s)(?: +(.*))?$'
                    pattern = template % (self.config.prefix, command)
                    regexp = re.compile(pattern)
                    self.bind_func(func.priority, regexp, func)
    
####################
# COMMAND DISPATCH #
####################
    
    def wrapped(self, origin, text, match): 
        return self.PhennyWrapper(self, origin, text, match)
    
    def input(self, origin, text, bytes, match, event, args): 
        return self.CommandInput(self, text, origin, bytes, match, event, args)
    
    def call(self, func, origin, phenny, input): 
        try: 
            func(phenny, input)
        except KeyboardInterrupt:
            raise
        except Exception, e: 
            traceback.print_exc()
            self.error(origin)
    
    def limit(self, origin, func): 
       if origin.sender and origin.sender.startswith('#'): 
           if hasattr(self.config, 'limit'): 
               limits = self.config.limit.get(origin.sender)
               if limits and (func.__module__ not in limits): 
                   return True
       return False
    
    def dispatch(self, origin, args): 
        bytes, event, args = args[0], args[1], args[2:]
        text = decode(bytes)
        if os.environ.get('SHOW_DISPATCH'):
            print "Dispatch: %r %r %r %r" % (event, args, origin, text)
        
        # File away activity
        if event in ('PRIVMSG', 'NOTICE'):
            #args[0] is the origin of the message as reported by IRC
            self.activity[args[0]] = (time.time(), origin)
        
        for priority in ('high', 'medium', 'low'): 
            items = self.commands[priority].items()
            for regexp, funcs in items: 
                for func in funcs: 
                    if event != func.event: 
                        continue
                    
                    match = regexp.match(text)
                    if match: 
                        if self.limit(origin, func):
                            print "Limited!" 
                            continue
                        
                        phenny = self.wrapped(origin, text, match)
                        input = self.input(origin, text, bytes, match, event, args)
                        
                        if func.thread: 
                            startdaemon(self.call, func, origin, phenny, input)
                        else:
                            self.call(func, origin, phenny, input)
                        
                        for source in [origin.sender, origin.nick]: 
                            # XXX: Should this be moved to a service module?
                            try: 
                                self.stats[(func.name, source)] += 1
                            except KeyError: 
                                self.stats[(func.name, source)] = 1
    
########################
# SERVICE MODULE HOOKS #
########################
    
    def extendclass(self, name, newcls):
        """p.extendclass(str, type) -> None
        Takes the type and extends the named class using it. The type must 
        inherit from the original type.
        
        These are the current classes:
        * CommandInput
        * PhennyWrapper
        
        This does some magic so that if multiple service hooks extend the same 
        class, they all get called.
        """
        assert name in ('CommandInput', 'PhennyWrapper')
        assert issubclass(newcls, globals()[name]) # Check inheritance
        
        # I've done console tests on this idea, and it seems to hold, even if repeated.
        
        oldcls = getattr(self, name)
        patch = type(newcls.__name__, (newcls, oldcls), {
            '__doc__': newcls.__doc__, 
            '__module__': '__patch__.'+newcls.__module__,
            })
        setattr(self, name, patch)
    
#####################
# STORAGE UTILITIES #
#####################
    
    def save_storage(self):
        print >> sys.stderr, "Saving storage..."
        for module in self.modules:
            if hasattr(module, 'storage') and hasattr(module.storage, 'flush'):
                #Save the data
                module.storage.flush()
    
    def handle_close(self):
         self.save_storage()
         #super(Phenny, self).handle_close()
         irc.Bot.handle_close(self) #OLDSTYLE: I hate oldstyle classes
    
####################
# ACTIVITY TRACKER #
####################
    
    #XXX: Should this get moved to a service module?
    def howstale(self, channel):
        """p.howstale(str) -> number
        Returns how long it's been (in seconds) since the channel has been active. If there is no data, None is returned.
        """
        if channel not in self.activity:
            return None
        else:
            t, o = self.activity[channel]
            return time.time() - t
   
if __name__ == '__main__': 
    print __doc__
