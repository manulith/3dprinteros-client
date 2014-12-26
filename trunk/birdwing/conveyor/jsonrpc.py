# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/jsonrpc.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2012 MakerBot Industries, LLC
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import StringIO
import codecs
import errno
import json
import logging
import inspect
import io
import os
import sys
import threading

import conveyor.event
import conveyor.json_reader
import conveyor.log
import conveyor.stoppable
import conveyor.job

def get_installed_methods(obj):
    for name, value in inspect.getmembers(obj):
        if inspect.ismethod(value) and getattr(value, '_jsonrpc', False):
            yield (name, value)

def install(jsonrpc, obj):
    for _tuple in get_installed_methods(obj):
        jsonrpc.addmethod(*_tuple)


class JsonRpcException(Exception):
    def __init__(self, code, message, data):
        Exception.__init__(self, code, message)
        self.code = code
        self.message = message
        self.data = data


class JsonRpc(conveyor.stoppable.StoppableInterface):
    """ JsonRpc handles a json stream, to gaurentee the output file pointer 
    gets entire valid JSON blocks of data to process, by buffering up data 
    into complete blocks and only passing on entirer JSON blocks 
    """
    def __init__(self, infp, outfp):
        """
        @param infp input file pointer must have .read() and .stop()
        @param outfp output file pointer. must have .write()
        """
        self._condition = threading.Condition()
        self._send_condition = threading.Condition()
        self._idcounter = 0
        self._infp = infp # contract: .read(), .stop(), .close()
        self._jsonreader = conveyor.json_reader.JsonRPCReader(
            self._jsonreadercallback)
        self._log = conveyor.log.getlogger(self)
        self._methods = {}
        self._methodsinfo={}
        self._outfp = outfp # contract: .write(str), .close()
        self._stopped = False
        self._jobs = {}
        writer_class = codecs.getwriter('UTF-8')
        self._outfp_writer = writer_class(self._outfp)
        self._raw_handler = None

    #
    # Common part
    #

    def _jsonreadercallback(self, indata):
        self._log.debug('indata=%r', indata)
        try:
            parsed = json.loads(indata)
        except ValueError:
            response = self._parseerror()
        else:
            if isinstance(parsed, dict):
                response = self._handleobject(parsed)
            elif isinstance(parsed, list):
                response = self._handlearray(parsed)
            else:
                response = self._invalidrequest(None)
        self._log.debug('response=%r', response)
        if None is not response:
            try:
                outdata = conveyor.json_reader.dumps(response)
                self._send(outdata)
            except UnicodeDecodeError as e:
                self._log.error('UnicodeDecodeError, response=%s', response, exc_info=True)

    def _handleobject(self, parsed):
        if not isinstance(parsed, dict):
            response = self._invalidrequest(None)
        else:
            id = parsed.get('id')
            if self._isrequest(parsed):
                response = self._handlerequest(parsed, id)
            elif self._isresponse(parsed):
                response = None
                self._handleresponse(parsed, id)
            else:
                response = self._invalidrequest(id)
        return response

    def _handlearray(self, parsed):
        if 0 == len(parsed):
            response = self._invalidrequest(None)
        else:
            response = []
            for subparsed in parsed:
                subresponse = self._handleobject(subparsed)
                if None is not subresponse:
                    response.append(subresponse)
            if 0 == len(response):
                response = None
        return response

    def _isrequest(self, parsed):
        result = (
            'jsonrpc' in parsed
            and '2.0' == parsed['jsonrpc']
            and 'method' in parsed
            and isinstance(parsed['method'], basestring))
        return result

    def _isresponse(self, parsed):
        result = (self._issuccessresponse(parsed)
            or self._iserrorresponse(parsed))
        return result

    def _issuccessresponse(self, parsed):
        result = (
            'jsonrpc' in parsed and '2.0' == parsed['jsonrpc']
            and 'result' in parsed)
        return result

    def _iserrorresponse(self, parsed):
        result = (
            'jsonrpc' in parsed and '2.0' == parsed['jsonrpc']
            and 'error' in parsed)
        return result

    def _successresponse(self, id, result):
        response = {'jsonrpc': '2.0', 'result': result, 'id': id}
        return response

    def _errorresponse(self, id, code, message, data=None):
        error = {'code': code, 'message': message}
        if None is not data:
            error['data'] = data
        response = {'jsonrpc': '2.0', 'error': error, 'id': id}
        return response

    def _parseerror(self):
        response = self._errorresponse(None, -32700, 'parse error')
        return response

    def _invalidrequest(self, id):
        response = self._errorresponse(id, -32600, 'invalid request')
        return response

    def _methodnotfound(self, id):
        response = self._errorresponse(id, -32601, 'method not found')
        return response

    def _invalidparams(self, id):
        response = self._errorresponse(id, -32602, 'invalid params')
        return response

    def _send(self, data, extra=None):
        """
        Nominally just send the string data, which will be UTF-8 encoded.
        If extra is not None, it should be a byte array to send immediately
        after data, before any other parallel calls to _send can complete.
        If wait is also not None, it should be a semaphore to acquire before
        sending extra.  (Typically this is waiting for a response to the
        JSONRPC request in data).
        """
        with self._send_condition:
            if self._stopped:
                return
            self._log.debug('write=%r', data)
            self._outfp_writer.write(data)

            if None is not extra:
                if not self._stopped:
                    self._outfp.write(extra)

    def _feed(self, data):
        """
        Feed a chunk of data to either to the main json parser or a custom raw
        data parser.  Every time the json parser yields we check if there is a
        custom parser; the custom parser is done as soon as it yields data.
        """
        while data:
            if None is self._raw_handler:
                for index in self._jsonreader.feed(data):
                    if None is not self._raw_handler:
                        data = data[index:]
                        break
                else:
                    return
            else:
                try:
                    data = self._raw_handler.send(data)
                    if data:
                        self._raw_handler.close()
                        self._raw_handler = None
                except StopIteration:
                    self._raw_handler = None
                    return

    def run(self):
        """ This loop will run until self._stopped is set true."""
        self._log.debug('starting')
        try:
            while not self._stopped:
                data = self._infp.read()
                self._log.debug("read=%r", data)
                self._feed(data)
        except EOFError:
            pass
        self._log.debug('ending')
        self.close()

    def stop(self):
        """ required as a stoppable object. """
        self._stopped = True
        self._infp.stop()

    def close(self):
        self._stopped = True
        try:
            self._infp.close()
        except:
            self._log.debug('handled exception', exc_info=True)
        try:
            self._outfp_writer.close()
        except:
            self._log.debug('handled exception', exc_info=True)

    #
    # Client part
    #

    def _handleresponse(self, response, id):
        self._log.debug('response=%r, id=%r', response, id)
        job = self._jobs.pop(id, None)
        if None is job:
            self._log.debug('ignoring response for unknown id: %r', id)
        elif self._iserrorresponse(response):
            error = response['error']
            job.fail(error)
        elif self._issuccessresponse(response):
            result = response['result']
            job.end(result)
        else:
            raise ValueError(response)

    def notify(self, method, params):
        self._log.debug('method=%r, params=%r', method, params)
        request = {'jsonrpc': '2.0', 'method': method, 'params': params}
        data = conveyor.json_reader.dumps(request)
        self._send(data)

    def request(self, method, params, extra=None):
        """ 
        Builds a jsonrpc request job.
        @param method: json rpc method to run as a job
        @param params: params for method
        @param extra: trailing non-json bytes to send immediately after
                      the json packet
        @return a Job object with methods setup properly
        """
        with self._condition:
            id = self._idcounter
            self._idcounter += 1
        self._log.debug('method=%r, params=%r, id=%r', method, params, id)
        def runningevent(job):
            request = {
                'jsonrpc': '2.0', 'method': method, 'params': params, 'id': id}
            data = conveyor.json_reader.dumps(request)
            self._send(data, extra)
        def stoppedevent(job):
            if id in self._jobs.keys():
                del self._jobs[id]
            else:
                self._log.debug('stoppeevent fail for id=%r', id)
        job = conveyor.job.Job(id, method)
        job.runningevent.attach(runningevent)
        job.stoppedevent.attach(stoppedevent)
        self._jobs[id] = job
        return job

    def set_raw_handler(self, generator):
        """
        Replace the json packet parser with a custom generator.  This can only
        be called safely _directly_ from a method invoked by this parser.
        @param generator: This is fed the incoming data with .send().  Once it
            has received all of the data it needs, it must stop iteration.
            If it instead receives more data than it requires, it must yield
            back the extra data, at which point it will be closed.
        """
        self._raw_handler = generator
        next(self._raw_handler)

    #
    # Server part
    #

    def _handlerequest(self, request, id):
        self._log.debug('request=%r, id=%r', request, id)
        method = request['method']
        if method in self._methods:
            func = self._methods[method]
            if 'params' not in request:
                response = self._invokemethod(id, func, (), {})
            else:
                params = request['params']
                if isinstance(params, dict):
                    response = self._invokemethod(id, func, (), params)
                elif isinstance(params, list):
                    response = self._invokemethod(id, func, params, {})
                else:
                    response = self._invalidparams(id)
        else:
            response = self._methodnotfound(id)
        return response

    def _fixkwargs(self, kwargs):
        kwargs1 = {}
        for k, v in kwargs.items():
            k = str(k)
            kwargs1[k] = v
        return kwargs1

    def _invokemethod(self, id, func, args, kwargs):
        self._log.debug(
            'id=%r, func=%r, args=%r, kwargs=%r', id, func, args, kwargs)
        response = None
        kwargs = self._fixkwargs(kwargs)
        try:
            result = func(*args, **kwargs)
        except TypeError as e:
            self._log.warning('handled exception', exc_info=True)
            if None is not id:
                response = self._invalidparams(id)
        except JsonRpcException as e:
            self._log.warning('handled exception', exc_info=True)
            if None is not id:
                response = self._errorresponse(id, e.code, e.message, e.data)
        except Exception as e:
            self._log.warning('uncaught exception', exc_info=True)
            if None is not id:
                e = sys.exc_info()[1]
                data = {'name': e.__class__.__name__, 'args': e.args}
                response = self._errorresponse(
                    id, -32000, 'uncaught exception', data)
        else:
            # nicholasbishop: here's my attempt to explain what's
            # going on here since damn is it confusing:
            #
            # In general conveyor's JSON-RPC methods return a simple
            # response like a string or an info dict. This is even
            # true for most jobs. Methods like slice() and print()
            # create jobs but format those jobs as JSON objects. The
            # client is then responsible for watching job update
            # notifications to see when the job ends.
            #
            # There is a special case when a JSON-RPC method directly
            # returns a Job object. When that happens, this code
            # attaches its own callback to the job's stop event. This
            # method (the one we're in, not the callback function)
            # returns None, and there's a conditional higher up the
            # stack that skips sending back the response if it's
            # None. The callback function is then responsible for
            # sending the real response when the job ends.
            if not isinstance(result, conveyor.job.Job):
                if None is not id:
                    response = self._successresponse(id, result)
            else:
                job = result
                def stoppedcallback(job):
                    if conveyor.job.JobConclusion.ENDED == job.conclusion:
                        response = self._successresponse(id, job.result)
                    elif conveyor.job.JobConclusion.FAILED == job.conclusion:
                        response = self._errorresponse(id, -32001, 'job failed', job.failure)
                    elif conveyor.job.JobConclusion.CANCELED == job.conclusion:
                        response = self._errorresponse(id, -32002, 'job canceled', None)
                    else:
                        raise ValueError(job.conclusion)
                    outdata = conveyor.json_reader.dumps(response)
                    self._send(outdata)
                job.stoppedevent.attach(stoppedcallback)
                job.start()
            self._log.debug('response=%r', response)
        return response

    def addmethod(self, method, func):
        self._log.debug('method=%r, func=%r', method, func)
        self._methods[method] = func

    def getmethods(self):
        return self._methods
