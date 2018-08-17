#!/usr/bin/env python
from ruamel.yaml import YAML
from collections import OrderedDict
import pprint
import traceback
import sys
from jira import JIRA
import json
import jsonpath
import re
import os
from dateutil import parser
import argparse
import logging


from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from httplib2 import Http


SCOPES = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/spreadsheets']
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Google Sheets API Python Quickstart'

log = logging.getLogger()
log.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler(sys.stdout)
log.addHandler(ch)

pp = pprint.PrettyPrinter(indent=4)

def get_credentials():
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir,
                                   'sheets.googleapis.com-python-quickstart.json')

    store = Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        credentials = tools.run_flow(flow, store, args)
        print('Storing credentials to ' + credential_path)

    return credentials


def value2cell(path,value,type='string',req=None, fmt="%m/%d/%y %H:%M:%S"):
    """
    Trasnforms a Jira variable value. Returns a String
    :param path: The Jira Api Path. Used for debugging reasons, when error occures
    :param value: The Jira Api value. Can be string, Array
    :param type: What type the value will be transformed to
    :param req: Apply a regular expression to the initial value
    :param fmt: Date formating. Used if type is Date.
    :return: a String to be set as cell value
    """
    # If not value, return an empty string
    if not value or value[0] is None or value is None:
        return ''

    #initiate the cell value
    cell = ''

    try:
        if type.lower() == 'string':
            # if value is a list , create a comma separated string
            tcell = ','.join(value) if isinstance(value, list) else value
            # If reqular expression,
            # return a comma separated string with all the findings
            if req:
                pattern = re.compile(req)
                matches = pattern.findall(tcell)
                cell = ','.join(matches)
            else:
                #Simply return the original value
                cell = tcell
        elif type.lower() == 'date':
            #If type is Date, convert date to chosen format
            mydate = value[0] if isinstance(value, list) else value
            cell = parser.parse(mydate).strftime(fmt) if mydate else ''
        elif type.lower() == 'seconds' or type.lower() == 'minutes':
            try:
                #Expect number of seconds and convert it to minutes
                cell = value[0]/60  if isinstance(value, list) else value/60
            except TypeError:
                #Return empty string, when initial value is not a valid number
                cell = ''
        elif type.lower() == 'list' or type.lower() == 'json':
            # return a json string
            cell = json.dumps(value)

        #Return the value of cell
        return cell
    except TypeError:
        #If typeError , be verbose !!
        print(traceback.format_exc())
        print(value,path)
        return ''

def jira_ses(jira_url,user,passwd,proxies=None):
    """
    Returns a jira object.
    :param jira_url: The url of the jira server
    :param user: Username
    :param passwd: Password
    :return: A JIRA session Object
    """
    try:
        j = JIRA('%s' % jira_url, basic_auth=('%s' % user, '%s' % passwd))
        if proxies:
            j.session_proxies = {'http': proxies['http'],'https':proxies['http']}
        return j
    except Exception as e:
        print(traceback.format_exc())
        sys.exit(2)


def filter2jql(jira_ses,filter_id):
    """
     Returns a JQL object from a filter id
    :param jira_ses: Jira Session Object
    :param filter_id:  Filter ID
    :return: Filter Name, Jql
    """
    filter = jira_ses.filter(filter_id)
    return {'name': filter.name, 'jql': filter.jql}


def getJiraData(jira_ses,jql,fields='',numResults=100,start=0):
    """
    Extracts data from a JQL.
    :param jira_session: A Jira session object
    :param jql: A JIRA Query Language String
    :param fields: Jira Fields separated by comma
    :param numResults: Number of Jira entries to return on each API call
    :return: An Array of Jira issues data
    """
    maxResults = numResults
    lines = []
    issues = jira_ses.search_issues(
        '%s' % jql,
        startAt=start,
        maxResults=maxResults,
        validate_query=True,
        fields=fields,
        json_result=True)
    return  issues

def get_fields(fields):
    """
    Get the jira field from the configuration, to be used as the query fields argument
    :param fields: The configured fields
    :return: a list of jira fields
    """
    #Get all Jira Api paths and return the Jira fields
    paths = [f['path'] for f in fields]
    jiraFields = []
    for path in paths:
        items = path.split('.')
        if len(items) == 1:
            jiraFields.append(items[0])
        else:
            jiraFields.append(items[1])
    return jiraFields

if __name__ == '__main__':

    arg = argparse.ArgumentParser('Jira UXE Reports',parents=[tools.argparser])
    arg.add_argument('-y', '--yaml', help="Yaml Report Configuration", default="report.yaml")

    args = arg.parse_args()
    #Create an orderDict to store configuration
    config = OrderedDict()
    with open(args.yaml) as y:
        yaml = YAML(typ='safe', pure=True)
        configs = yaml.load(y)

    #Set number of item to be requested on each jira api call
    numResults = configs['NumResults']

    #Create a Jira Session
    myjira = jira_ses(configs['JiraURL'], 'a user', 'a passwd')

    #Authenticate and Create a Google Api session
    creds = get_credentials()
    SHEETS = discovery.build('sheets', 'v4', http=creds.authorize(Http()))

    #For each configured report:
    for config in configs['reports']:
        # Get Jira query from the Jira Filter ID
        myjql = filter2jql(myjira,config['jql'])
        #Create an list to store the jira Data
        rows = []
        #Create a list to keep the header fields and added first to the rows list
        header = []
        names = [f['name'] for f in config['fields']]
        rows.append(names)
        header.append(names)
        #Get query fields
        queryFields = get_fields(config['fields'])

        start = 0
        #Make jira api call untill all data  have been fetched
        while True:

            mydata = getJiraData(myjira, myjql['jql'], numResults=numResults,fields=queryFields, start=start)
            total = mydata['total']
            if start < total:
                for issue in mydata['issues']:
                    row = []
                    for f in config['fields']:
                        try:
                            field = f['path']
                            fmt = f['format'] if 'format' in f.keys() else \
                                "%m/%d/%y %H:%M:%S"
                            req = f['req'] if 'req' in f.keys() else \
                                None
                            rawvalue = jsonpath.jsonpath(issue,field)
                            row.append(value2cell(field,rawvalue, f['type'], req=req, fmt=fmt))
                        except KeyError:
                            print(traceback.format_exc())
                            row.append(rawvalue)
                        except:
                            print(traceback.format_exc())
                            print rawvalue

                    rows.append(row)
                start += numResults
            else:
                try:
                    data = {'values': rows}
                    clear_values_request_body = {}
                    SHEETS.spreadsheets().values().update(spreadsheetId=config['Spreadsheet'],
                                              range='%s' % config['Sheet'], body=data, valueInputOption='USER_ENTERED').execute()
                except Exception as e:
                    print(traceback.format_exc())
                break
