#  FreeRADIUS Python VLAN Module

This is a FreeRADIUS module written in Python for assigning VLANs to devices connecting to a wireless network. Source is available at [https://github.com/riskybacon/freeradius](https://github.com/riskybacon/freeradius)

Install the module in /usr/lib64/python/ldap2vlan.py. Add an integer attribute to your LDAP schema called x-nmc-priority to support the ordering of LDAP entities.

## Requirements

When I wrote this module for [The New Mexico Consortium](http://newmexicoconsortium.org), the server infrastructure and data was already in place. I just needed to add some glue. We needed a piece of software that would:

* Query the LDAP database:
 * Take username and MAC address as input
 * Look at LDAP groups for VLAN tags
 * Output a VLAN tag
* Insert a response into the RADIUS response packet with the VLAN tag information
* Prioritize VLAN assignment. Users can belong to multiple groups. Assign the VLAN from the group with the lowest priority number
* Check for known MAC addresses. The MAC address of the device must be known to assign anything other than the guest VLAN

## Existing infrastructure:

 * [Xirrus](http://www.xirrus.com/) APs using RADIUS for authentication
 * [FreeRADIUS](http://freeradius.org) providing the RADIUS service
 * A mix of clients, mostly iPhones, Apple laptops, Linux laptops and some Windows laptops
 * [OpenLDAP](http://www.openldap.org/OpenLDAP) with the FreeRADIUS schema installed, and some local schema changes. No passwords stored in LDAP
 * [MIT Kerberos](http://web.mit.edu/kerberos) for the password store
 * The arcfour-hmac:normal hash stored in our Kerberos DB for Windows client support
 * [Kerberos Challenge Response Authentication Protocol](http://http://www.spock.org/kcrap/) for Windows client support

Versions:

* CentOS 6.5
* FreeRadius 2.1.12 + kcrap patch
* OpenLDAP 2.4.23
* Kerberos 1.6.1

## Implementation

I decided to use the FreeRADIUS module system. The documentation raises more questions than it answers. Luckily, the FreeRADIUS source code is nicely organized and readable. The section I needed to hook into is post-auth.

Steps to set up:

* Add an LDAP attribute to set a group's priority
* Install the Python module that takes a user ID and MAC address and returns a VLAN tag
* Configure FreeRADIUS to use the Python module

The last two steps are what were interesting to me. The FreeRADIUS search path isn't discussed, and the input to the module isn't described and the required output isn't documented.

## FreeRADIUS Python VLAN Module

The keys to making the module work are:

* Placing the module in the right location
* Returning an appropriate tuple in the post_auth function
* Configuring FreeRADIUS to use the module

The host I was using runs CentOS 6.5 and Python 2.6. The right location for the module turned out to be /usr/lib64/python2.6/ldap2vlan.py. I'm sure there are other places that would also work.

Returning an appropriate tuple is not documented. The post-auth function needs to return a 3-tuple with the following elements:

1. A 1-tuple containing the constant radiusd.RLM_MODULE_UPDATED,
2. An n-tuple of 2-tuples
3. (‘Post-Auth-Type’, ‘python’)

The second tuple contains the key-value pairs are inserted into the RADIUS response packet. For example, an entire response might look like:

```bash
(radiusd.RLM_MODULE_UPDATED, 
( ('Tunnel-Private-Group-Id', 92),
  ('Tunnel-Type', 'VLAN'),
  ('Tunnel-Medium-Type', 'IEEE-802')
),
('Post-Auth-Type', 'python')
```

I wanted other members of the team to be able to troubleshoot problems with RADIUS, LDAP and VLAN assignment, so I added some troubleshooting to the module. I did this by also making the module callable from the commandline. Examples:

To show the VLAN that will be assigned to a user / mac address pair:
```bash
ldap2vlan username mac-address
```

To show the VLAN-enabled groups that a user belongs to:
```bash
ldap2vlan username
```

Show all groups in LDAP that provide VLAN information, sorted:
```bash
ldap2vlan
```

## FreeRADIUS configuration

In <strong> /etc/raddb/modules/python</strong>:
```bash
python {
	mod_instantiate = "ldap2vlan"
	func_instantiate = "instantiate"

	mod_post_auth = "ldap2vlan"
	func_post_auth = "post_auth"

	mod_detach = "ldap2vlan"
	func_detach = "detach"
}
```

In */etc/raddb/sites-available/default*, change the post-auth section to be:

```bash
{% highlight bash %}
post-auth {
	python
}
```

Put the following into */usr/lib64/python2.6/site-packages/radiusd.py*

```bash
#
# Definitions for RADIUS programs
#
# Copyright 2002 Miguel A.L. Paraz <mparaz@mparaz.com>
#
# This should only be used when testing modules.
# Inside freeradius, the 'radiusd' Python module is created by the C module
# and the definitions are automatically created.
#
# $Id$

# from modules.h

RLM_MODULE_REJECT = 0
RLM_MODULE_FAIL = 1
RLM_MODULE_OK = 2
RLM_MODULE_HANDLED = 3
RLM_MODULE_INVALID = 4
RLM_MODULE_USERLOCK = 5
RLM_MODULE_NOTFOUND = 6
RLM_MODULE_NOOP = 7     
RLM_MODULE_UPDATED = 8
RLM_MODULE_NUMCODES = 9


# from radiusd.h
L_DBG = 1
L_AUTH = 2
L_INFO = 3
L_ERR = 4
L_PROXY = 5
L_CONS = 128


# log function
def radlog(level, msg):
    import sys
    sys.stdout.write(msg + 'n')

    level = level
```

A better file is supposed to be generated when FreeRADIUS is built. This doesn't happen, but I found that the test file works fine.
