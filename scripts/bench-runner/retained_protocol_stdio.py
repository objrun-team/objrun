"""Keep protocol pipes independent of pytest's later dup2 capture of fd0/1.

The caller retains its original framing, size bounds, authentication and scoring.
No capture setting or subprocess policy is changed.
"""
import os
import sys


def retain_protocol_stdio():
    input_fd = os.dup(sys.stdin.fileno())
    output_fd = None
    protocol_input = None
    try:
        output_fd = os.dup(sys.stdout.fileno())
        protocol_input = os.fdopen(input_fd, 'rb')
        input_fd = None
        protocol_output = os.fdopen(output_fd, 'w', encoding='utf-8', newline='\n')
        output_fd = None
        return protocol_input, protocol_output
    except BaseException:
        if protocol_input is not None:
            protocol_input.close()
        if input_fd is not None:
            os.close(input_fd)
        if output_fd is not None:
            os.close(output_fd)
        raise
