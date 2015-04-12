A FreeRADIUS module, written in Python, that uses data in LDAP to
assign a VLAN.

You can read more at http://riskybacon.github.io/2015/03/08/freeradius-python-vlan-module/

This module assumes that there are some local modifications to your LDAP database, specifically the x-nmc-priority attribute which allows for entries to be sorted after they have been fetched from the database.

Tested on CentOS 6.5. Place this module in /usr/lib64/python2.6/ldap2vlan.py

This work was performed for the <a href = "http://newmexicoconsortium.org">New Mexico Consortium</a>
