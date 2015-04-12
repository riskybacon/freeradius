#!/usr/bin/python
#-------------------------------------------------------------------------------
# FreeRADIUS module to assign a VLAN ID based on the mac address
# and username
#
# If the MAC address is known, get the list of groups to which
# the user belongs, the groups that define vlans, and use the
# group that has the lowest priority number to assign the vlan
#
# Otherwise, get the list of all groups that provide VLAN information,
# and use the group with the  highest priority number to set the VLAN
#-------------------------------------------------------------------------------
import radiusd, syslog, os, sys, ldap, socket, urlparse

# LDAP server to use
ldapServers = ['ldaps://ldap1.yourdomain.com',
               'ldaps://ldap2.yourdomain.com']

# Base DN to search
baseDN = 'dc=yourdomain,dc=com'

# Groups subtree
groupDN = 'ou=Group' + ',' + baseDN

# Hosts subtree
hostDN = 'ou=Hosts' + ',' + baseDN

# Search filter and attributes for VLANs
groupFilter = 'objectClass=radiusprofile'

# The on which groups/vlans are sorted
groupPrioritySortKey = 'x-nmc-priority'

#-------------------------------------------------------------------------------
# Called when FreeRADIUS starts
#-------------------------------------------------------------------------------
def instantiate(p):
  syslog.syslog('ldap2vlan FreeRADIUS module instantiated')

#-------------------------------------------------------------------------------
# Called by FreeRADIUS during the post_auth phase
#-------------------------------------------------------------------------------
def post_auth(tupleList):
  try:
    # Convert the list of RADIUS request packet tuples into a dictionary
    # for easy lookup
    request = tupleListToDict(tupleList)
    mac = request['Calling-Station-Id'];
    username = request['User-Name']
 
    # MAC addrs come in the form: "00-26-08-E8-90-F1"
    # We need them to be lowercased, dashes replaced with colons and
    # the quotation marks removed
    mac = saneMac(mac)

    # Usernames have quotation marks around them. 
    # Impose sanity
    username = saneUsername(username)

    # Assign a VLAN
    vlan = vlanLookup(username, mac)

    # Return the VLAN
    return (radiusd.RLM_MODULE_UPDATED,
            (
             ('Tunnel-Private-Group-Id', vlan),
             ('Tunnel-Type', 'VLAN'),
             ('Tunnel-Medium-Type', 'IEEE-802'),
            ),
	    (
             ('Post-Auth-Type', 'python'),
            )
           )
  except:
    e = sys.exc_info()[0]
    syslog(e)

  # If execution gets here, something is wrong. Fail closed
  # eg, no access if things are broken. Devices could end up
  # on a privileged VLAN
  return radiusd.RLM_MODULE_REJECT

#-------------------------------------------------------------------------------
# Called when FreeRADIUS exits
#-------------------------------------------------------------------------------
def detach(p):
  syslog.syslog('ldap2vlan FreeRADIUS module detach')
  return radiusd.RLM_MODULE_OK

#-------------------------------------------------------------------------------
# Turn a request packet list of tuples into a dictionary. This is much
# easier to deal with
#
# @param tupleList - a list of tuples in format ((attribute, value), ...)
#
# @return A dictionary that maps attribute names to values
#-------------------------------------------------------------------------------
def tupleListToDict(tupleList):
  # Initialize empty dictionary
  dict = {}

  try:
    for tuple in tupleList:
      dict[tuple[0]] = tuple[1]
  except:
    e = sys.exc_info()[0]
    syslog(e)

  return dict

#-------------------------------------------------------------------------------
# Change "00-26-08-E8-90-F1" into 00:26:08:e8:90:f1
#-------------------------------------------------------------------------------
def saneMac(mac):
  # Remove quotation marks
  mac = mac.replace('"', '')
  # Replace dashes with colons
  mac = mac.replace('-', ':')
  # Lower case the string
  return mac.lower()

#-------------------------------------------------------------------------------
# Remove quotes from username
#-------------------------------------------------------------------------------
def saneUsername(user):
  return user.replace('"', '')

#-------------------------------------------------------------------------------
# Lookup the VLAN in database
#-------------------------------------------------------------------------------
def vlanLookup(username, mac):
  con = ldapConnect()
  vlan = None

  # Look up this MAC addr in the hosts subtree. The hosts() function
  # returns a list of LDAP entries that match this mac addr.
  if hosts(con, mac):
    # If the MAC address is known, get the list of groups to which
    # this user belongs, the groups that define vlans, and use the
    # group that has the lowest priority number to assign the vlan
    groups = userVlanGroups(con, username)

    # It is possible that the user does not belong to any
    # groups that define vlan access. Verify that groups
    # were returned before assigning the vlan
    if groups:
      # groups are returned as a list of dictionaries. Pull the
      # radiusTunnelPrivateGroupId out of each dictionary in the list
      # and build an list of vlans
      vlans = map((lambda x: x['radiusTunnelPrivateGroupId'][0]), groups)
      vlan = vlans[0]
      vlanStr = ','.join(str(x) for x in vlans)
    else:
      message = '%s not a member of any vlan groups' % username
      syslog.syslog(message)
  else:
    message = "%s/%s: mac addr not in ldap" % (username, mac)
    syslog.syslog(message)

  # Catch-all case: the vlan was not set, so assign
  # the guest vlan, which is defined as the vlan with
  # the highest priority number
  if not vlan:
    vlan = guestVlan(con)
    message = 'no vlans found for %s/%s, assigning vlan %s' % (username, mac, vlan)
    syslog.syslog(message)
    vlanSet = True
   
  con.unbind_s()

  return vlan

#-------------------------------------------------------------------------------
# @param  URL for ldap server in form [protocol]://hostname:port
# @return the hostname portion of the ldap string
#-------------------------------------------------------------------------------
def urlHostname(url):
  hostnameAndPort = urlparse.urlparse(url).netloc
  parts = hostnameAndPort.split(':')

  if parts:
    return parts[0]
  
  return None
  
#-------------------------------------------------------------------------------
# Connect to the LDAP server anonymously
#
# @return An LDAP object
#-------------------------------------------------------------------------------
def ldapConnect():
  '''Connect to the LDAP server'''
  con = None
  hostname = None
  for server in ldapServers:
    print "trying server %s" % server
    try:
      # con will be a valid LDAP connection object
      # even if the server is for an unknown host. It
      # will not throw an exception, so this error will
      # go undetected.
      #
      # To work around this, we call socket.gethostbyname()
      hostname = urlHostname(server)
      ip = socket.gethostbyname(hostname)
      con = ldap.initialize(server)
      # Simple bind, no credentials. 
      con.simple_bind_s()
      return con
    except ldap.LDAPError, e:
      message = 'error connecting to %s: %s' % (server, str(e))
      print (message)
      syslog.syslog(message)
      con = None
    except socket.error, e:
      message = 'host %s: %s' % (hostname, str(e))
      print (message)
      syslog.syslog(message)
      con = None
 
  return con

#-------------------------------------------------------------------------------
# Find the entire list of groups with VLAN information
#
# @param con The LDAP connection
# 
# @return sorted sorted array of LDAP groups
#-------------------------------------------------------------------------------
def vlanGroups(con):
  '''Find the groups in LDAP that provide vlan information'''
  filter="(&(objectClass=radiusprofile)(&(objectClass=x-nmc-vlan)))"
  return sortGroups(search(con, groupDN, filter))

#-------------------------------------------------------------------------------
# Find a list of groups to which the user belongs that provide
# RADIUS attributes to set the VLAN
#
# @param con   The LDAP connection
# @param user  The username for the search. 
#
# @return sorted sorted array of LDAP groups
#-------------------------------------------------------------------------------
def userVlanGroups(con, user):
   filter='(&(' + groupFilter + ')(&(memberUid=' + user + ')))'
   return sortGroups(search(con, groupDN, filter))

#-------------------------------------------------------------------------------
# Get the guest vlan from the groups in LDAP. 
#
# @param con   The LDAP connection
#
# @return guest VLAN attributes
#-------------------------------------------------------------------------------
def guestVlan(con):
  # The Guest vlan has the highest numbered priority. 
  # Retrieve all VLAN groups and return the last one in the list
  return vlanGroups(con)[-1]['radiusTunnelPrivateGroupId'][0]

#-------------------------------------------------------------------------------
# Sort a list of groups by their priority number, ascending
#
# @param groupList   The list of groups to sort
#
# @return The sorted groups
#-------------------------------------------------------------------------------
def sortGroups(groupList):
  return sorted(groupList, key=groupSortKey)

#-------------------------------------------------------------------------------
# The sort key function for groups
#
# @param group The group for which the key should be retrieved
#
# @return the value on which to sort
#-------------------------------------------------------------------------------
def groupSortKey(group):
  if groupPrioritySortKey in group: 
    return int(group[groupPrioritySortKey][0])

  message = 'group %s does not have sort key %s as an attribute, vlans will not be assigned properly. Either the group was incorrectly entered into LDAP or the LDAP schema does not allow for this property to be added to the group.' % (group['cn'], groupPrioritySortKey)

  print (message)
  print ('')
  syslog.syslog(message)
  return 1000

#-------------------------------------------------------------------------------
# Find all ou=Hosts entries in the LDAP db that match
# x-nmc-macToIp
#-------------------------------------------------------------------------------
def hosts(con, mac):
  '''Return set of LDAP entries in ou=Hosts that have this mac address'''
  hostSearchFilter='(&(x-nmc-macToIp=' + mac + '))'
  return search(con, hostDN, hostSearchFilter)

#-------------------------------------------------------------------------------
# Search an LDAP subtree for objects
#
# @param con     The LDAP connection
# @param dn      The subtree to search, example: ou=Hosts,dc=domain,dc=com
# @param filter  Search filter, example (&(x-nmc-macTo=78:31:c1:b8:41:a0))
# 
# @return An array of results, if any were found
#-------------------------------------------------------------------------------
def search(con, dn, filter):
  '''Search a subtree for objects that match the filter.'''
  # Initialize variables
  results, result = [], []
  processResults = True
  # Perform the search
  resultId = con.search(dn, ldap.SCOPE_SUBTREE, filter)

  # Loop over the results
  while processResults:
    resultType, result = con.result(resultId, 0)
    if result and resultType == ldap.RES_SEARCH_ENTRY:
      results.append(result[0][1])
    else:
      processResults = False;

  return results

#-------------------------------------------------------------------------------
# Print a list of VLANs in a nice format. Takes the groups
# output from the search() function as input
#
# @param groups - set of groups returned from the search() function
#-------------------------------------------------------------------------------
def printVlanTuples(groups):
  # Build list of 3-tuples (cn, priority, vlan id)
  vlans =  map((lambda x: (x['cn'][0],
                       x['x-nmc-priority'][0],
                       x['radiusTunnelPrivateGroupId'][0])),
               groups)

  print ("")
  print ("(group, priority, vlan tag):")
  print ("------------------------------")

  for vlan in vlans:
    print vlan


#-------------------------------------------------------------------------------
# List the vlans for a user
#-------------------------------------------------------------------------------
def listVlansForUser(con, username, mac = None):
  vlans = userVlanGroups(con, username)

  print ("List of vlans for %s in sorted order:" % username)
  printVlanTuples(vlans)
  print ("Guest group not listed, don't go add this person that group")

  # A mac addr was provided, check to see what vlan will be
  # assigned to this user/vlan pair
  if mac:
    if not hosts(con, mac):
       print ('')
       print ("Possible problem: %s not in LDAP " % mac)
       print ('Verify with:')
       print ('ldapsearch -x -b %s "(&(x-nmc-macToIp=%s))"') % (hostDN, mac)
       print ('It can take some time for a mac address to show up for ldap2vlan')
       print ('But it shows up immediately in the LDAP search. This is baffling')

  else:
    mac = 'no_mac'

  radiusPacket = ( ('Calling-Station-Id', mac),
                   ('User-Name', username),
                 )
  vlan = post_auth(radiusPacket)

  print ('')
  print ('%s/%s RADIUS VLAN attributes:' % (username, mac))
  print ('')
  print (vlan[1])

#-------------------------------------------------------------------------------
# Prints out all vlan groups in ldap
#-------------------------------------------------------------------------------
def listVlans(con):
  # Build list of 3-tuples (cn, priority, vlan id)
  vlans = vlanGroups(con)

  print ("List of vlans in sorted order. The lowest priority number is given")
  print ("precedence when assigning a vlan id to a user.")
  print ("")
  print ("The guest group should be the last one")
  print ("in this list. If it isn't, you have problems.")
  print ("")

  printVlanTuples(vlans)

#-------------------------------------------------------------------------------
# Allow this module to be called as a command line utility
# to troubleshoot VLAN assignment problems. All arguments are optional
#
# Usage: ldap2vlan [username] [mac addr]
#-------------------------------------------------------------------------------
if __name__ == '__main__':
  con = ldapConnect()

  # Get the username off of the command line, if it 
  # was specified
  username = None
  if len(sys.argv) == 2:
    username = sys.argv[1]
    listVlansForUser(con, username)
  elif len(sys.argv) == 3:
    username = sys.argv[1]
    mac = saneMac(sys.argv[2])
    listVlansForUser(con, username, mac)
  else:
    listVlans(con)

  con.unbind_s()
