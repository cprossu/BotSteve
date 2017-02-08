#!/usr/bin/env python
"""
greet.py - Phenny User Greeting Module
Copyright 2011, James Bliss, astro73.com
Licensed under the Eiffel Forum License 2.

http://github.com/Steve-V/tgg-BotSteve
"""
import random
def join_greeter(phenny, input):
    """
    Greets users based on options in the datastore.
    """
    global storage
    
    #print "%s joined %s" % (input.nick, input.sender)
    
    nick = str(input.nick)
    ginfo = storage.get(nick.lower())
    #NICKTRACKER: Check the canonical nick of the real nick fails.
    if hasattr(phenny, 'nicktracker') and not ginfo and input.canonnick:
        ginfo = storage.get(input.canonnick.lower())
    if ginfo:
        if random.randint(1,100) <= int(ginfo['chance']):
            phenny.say(random.choice(ginfo['greets']))

join_greeter.event = 'JOIN'
join_greeter.rule = r'(.*)'
join_greeter.priority = 'low'


if __name__ == '__main__': 
   print __doc__.strip()
