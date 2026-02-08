"""
Stream routes - Server-Sent Events for real-time analysis
"""

import json
from flask import Blueprint, Response
from ..models import Run
from ..agents.analyzer import XRayAnalyzer

stream_bp = Blueprint('stream', __name__)


@stream_bp.route('/api/analyze/<run_id>/stream', methods=['GET'])
def stream_analysis(run_id):
    """
    Stream analysis results via Server-Sent Events.
    
    Each window result is sent as an SSE event as it completes:
    - event: window - partial result for each step transition
    - event: complete - final combined analysis
    - event: error - if something goes wrong
    
    Returns:
        text/event-stream response
    """
    run = Run.query.get(run_id)
    if not run:
        def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': 'Run not found'})}\n\n"
        return Response(error_stream(), mimetype='text/event-stream')
    
    def generate():
        try:
            analyzer = XRayAnalyzer()
            run_dict = run.to_dict(include_steps=True)
            
            for event in analyzer.analyze_run_streaming(run_dict):
                event_type = event.get('event', 'message')
                event_data = json.dumps(event.get('data', {}), default=str)
                yield f"event: {event_type}\ndata: {event_data}\n\n"
                
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )
