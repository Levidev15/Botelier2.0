"""
Flow Templates - Pre-built conversation flows for hotels.

These templates provide starting points that hotels can customize
in the visual editor:

1. FAQ Bot - Answers guest questions using knowledge base
2. Booking Flow - Guided room reservation process
3. Transfer Flow - Smart call routing to departments
4. Concierge Flow - Full-service guest assistance
"""

from typing import Any, Dict
from botelier.voice.flows.engine import FlowNodeBuilder


class FlowTemplates:
    """Pre-built flow templates for hotels."""
    
    @staticmethod
    def get_template(template_name: str) -> Dict[str, Any]:
        """Get a flow template by name."""
        templates = {
            "faq_bot": FlowTemplates.faq_bot(),
            "booking_flow": FlowTemplates.booking_flow(),
            "transfer_flow": FlowTemplates.transfer_flow(),
            "concierge_flow": FlowTemplates.concierge_flow(),
        }
        return templates.get(template_name, FlowTemplates.faq_bot())
    
    @staticmethod
    def list_templates() -> list:
        """List available template metadata."""
        return [
            {
                "id": "faq_bot",
                "name": "FAQ Bot",
                "description": "Answers guest questions using knowledge base",
                "complexity": "simple",
                "nodes_count": 2
            },
            {
                "id": "booking_flow",
                "name": "Booking Flow",
                "description": "Guided room reservation with availability check",
                "complexity": "medium",
                "nodes_count": 5
            },
            {
                "id": "transfer_flow",
                "name": "Transfer Flow",
                "description": "Smart call routing to hotel departments",
                "complexity": "simple",
                "nodes_count": 3
            },
            {
                "id": "concierge_flow",
                "name": "Concierge Flow",
                "description": "Full-service guest assistance with multiple capabilities",
                "complexity": "complex",
                "nodes_count": 7
            }
        ]
    
    @staticmethod
    def faq_bot() -> Dict[str, Any]:
        """
        Simple FAQ bot that answers questions using knowledge base.
        
        Flow:
        greeting → (query_knowledge) → greeting (loops)
                 → (end_call) → end
        """
        greeting = (
            FlowNodeBuilder("greeting", "Greeting")
            .with_role_message(
                "You are a helpful hotel assistant. Answer guest questions "
                "accurately and concisely using the hotel's knowledge base."
            )
            .with_task_message(
                "Greet the caller warmly and ask how you can help them today."
            )
            .with_function(
                name="query_hotel_knowledge",
                description="Search the hotel knowledge base to answer guest questions",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The guest's question"
                        }
                    },
                    "required": ["question"]
                },
                transition_to="greeting"
            )
            .with_function(
                name="end_call",
                description="End the call when the guest is finished or says goodbye",
                transition_to="end"
            )
            .build()
        )
        
        end = (
            FlowNodeBuilder("end", "End Call")
            .with_task_message(
                "Thank the guest and wish them a pleasant stay."
            )
            .as_end_node()
            .build()
        )
        
        return {
            "initial_node": "greeting",
            "nodes": [
                {"id": "greeting", "type": "initial", "data": greeting, "position": {"x": 100, "y": 100}},
                {"id": "end", "type": "end", "data": end, "position": {"x": 100, "y": 300}}
            ],
            "edges": [
                {"id": "e1", "source": "greeting", "target": "end"}
            ]
        }
    
    @staticmethod
    def booking_flow() -> Dict[str, Any]:
        """
        Multi-step room booking flow.
        
        Flow:
        greeting → collect_dates → collect_room_type → check_availability → confirm → end
        """
        greeting = (
            FlowNodeBuilder("greeting", "Greeting")
            .with_role_message(
                "You are a hotel reservation specialist. Help guests book rooms "
                "by collecting their preferences step by step."
            )
            .with_task_message(
                "Greet the caller and ask if they would like to make a reservation."
            )
            .with_function(
                name="start_booking",
                description="Guest wants to make a room reservation",
                transition_to="collect_dates"
            )
            .with_function(
                name="query_hotel_knowledge",
                description="Answer general questions about the hotel",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "The question"}
                    },
                    "required": ["question"]
                },
                transition_to="greeting"
            )
            .with_function(
                name="end_call",
                description="End the call",
                transition_to="end"
            )
            .build()
        )
        
        collect_dates = (
            FlowNodeBuilder("collect_dates", "Collect Dates")
            .with_task_message(
                "Ask the guest for their check-in and check-out dates."
            )
            .with_function(
                name="save_dates",
                description="Guest has provided check-in and check-out dates",
                parameters={
                    "type": "object",
                    "properties": {
                        "check_in": {"type": "string", "description": "Check-in date"},
                        "check_out": {"type": "string", "description": "Check-out date"}
                    },
                    "required": ["check_in", "check_out"]
                },
                transition_to="collect_room_type"
            )
            .build()
        )
        
        collect_room_type = (
            FlowNodeBuilder("collect_room_type", "Collect Room Type")
            .with_task_message(
                "Ask the guest what type of room they prefer "
                "(standard, deluxe, suite, etc.) and number of guests."
            )
            .with_function(
                name="save_room_preference",
                description="Guest has specified room type and guests",
                parameters={
                    "type": "object",
                    "properties": {
                        "room_type": {"type": "string", "description": "Room type preference"},
                        "num_guests": {"type": "integer", "description": "Number of guests"}
                    },
                    "required": ["room_type", "num_guests"]
                },
                transition_to="check_availability"
            )
            .build()
        )
        
        check_availability = (
            FlowNodeBuilder("check_availability", "Check Availability")
            .with_task_message(
                "Check room availability and present options to the guest. "
                "Include pricing if available."
            )
            .with_function(
                name="check_room_availability",
                description="Check if rooms are available for the requested dates",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                transition_to="confirm"
            )
            .with_function(
                name="modify_dates",
                description="Guest wants to change their dates",
                transition_to="collect_dates"
            )
            .build()
        )
        
        confirm = (
            FlowNodeBuilder("confirm", "Confirm Booking")
            .with_task_message(
                "Summarize the booking details and ask the guest to confirm. "
                "Collect their name and contact information."
            )
            .with_function(
                name="confirm_booking",
                description="Guest confirms the reservation",
                parameters={
                    "type": "object",
                    "properties": {
                        "guest_name": {"type": "string", "description": "Guest name"},
                        "phone": {"type": "string", "description": "Contact phone"},
                        "email": {"type": "string", "description": "Email (optional)"}
                    },
                    "required": ["guest_name", "phone"]
                },
                transition_to="end"
            )
            .with_function(
                name="cancel_booking",
                description="Guest decides not to book",
                transition_to="greeting"
            )
            .build()
        )
        
        end = (
            FlowNodeBuilder("end", "Booking Complete")
            .with_task_message(
                "Confirm the booking was created and provide a confirmation number. "
                "Thank the guest and wish them a pleasant stay."
            )
            .as_end_node()
            .build()
        )
        
        return {
            "initial_node": "greeting",
            "nodes": [
                {"id": "greeting", "type": "initial", "data": greeting, "position": {"x": 250, "y": 50}},
                {"id": "collect_dates", "type": "node", "data": collect_dates, "position": {"x": 250, "y": 200}},
                {"id": "collect_room_type", "type": "node", "data": collect_room_type, "position": {"x": 250, "y": 350}},
                {"id": "check_availability", "type": "node", "data": check_availability, "position": {"x": 250, "y": 500}},
                {"id": "confirm", "type": "node", "data": confirm, "position": {"x": 250, "y": 650}},
                {"id": "end", "type": "end", "data": end, "position": {"x": 250, "y": 800}}
            ],
            "edges": [
                {"id": "e1", "source": "greeting", "target": "collect_dates"},
                {"id": "e2", "source": "collect_dates", "target": "collect_room_type"},
                {"id": "e3", "source": "collect_room_type", "target": "check_availability"},
                {"id": "e4", "source": "check_availability", "target": "confirm"},
                {"id": "e5", "source": "confirm", "target": "end"},
                {"id": "e6", "source": "check_availability", "target": "collect_dates"},
                {"id": "e7", "source": "confirm", "target": "greeting"}
            ]
        }
    
    @staticmethod
    def transfer_flow() -> Dict[str, Any]:
        """
        Call routing flow that transfers to appropriate departments.
        
        Flow:
        greeting → (identify_department) → transfer → end
        """
        greeting = (
            FlowNodeBuilder("greeting", "Greeting")
            .with_role_message(
                "You are a hotel operator. Help callers reach the right department "
                "or person. Be efficient but friendly."
            )
            .with_task_message(
                "Greet the caller and ask how you can direct their call."
            )
            .with_function(
                name="transfer_to_front_desk",
                description="Transfer to front desk for check-in, check-out, room issues",
                transition_to="transfer"
            )
            .with_function(
                name="transfer_to_concierge",
                description="Transfer to concierge for reservations, recommendations",
                transition_to="transfer"
            )
            .with_function(
                name="transfer_to_housekeeping",
                description="Transfer to housekeeping for room cleaning, amenities",
                transition_to="transfer"
            )
            .with_function(
                name="transfer_to_room_service",
                description="Transfer to room service for food orders",
                transition_to="transfer"
            )
            .with_function(
                name="query_hotel_knowledge",
                description="Answer simple questions without transfer",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"}
                    },
                    "required": ["question"]
                },
                transition_to="greeting"
            )
            .build()
        )
        
        transfer = (
            FlowNodeBuilder("transfer", "Transferring")
            .with_task_message(
                "Confirm the transfer and let the caller know you're connecting them."
            )
            .with_function(
                name="complete_transfer",
                description="Transfer is complete",
                transition_to="end"
            )
            .build()
        )
        
        end = (
            FlowNodeBuilder("end", "Call Complete")
            .as_end_node()
            .build()
        )
        
        return {
            "initial_node": "greeting",
            "nodes": [
                {"id": "greeting", "type": "initial", "data": greeting, "position": {"x": 250, "y": 100}},
                {"id": "transfer", "type": "node", "data": transfer, "position": {"x": 250, "y": 300}},
                {"id": "end", "type": "end", "data": end, "position": {"x": 250, "y": 500}}
            ],
            "edges": [
                {"id": "e1", "source": "greeting", "target": "transfer"},
                {"id": "e2", "source": "transfer", "target": "end"}
            ]
        }
    
    @staticmethod
    def concierge_flow() -> Dict[str, Any]:
        """
        Full-service concierge with multiple capabilities.
        
        Flow:
        greeting → [booking | inquiry | transfer | dining | activities] → follow_up → end
        """
        greeting = (
            FlowNodeBuilder("greeting", "Greeting")
            .with_role_message(
                "You are a luxury hotel concierge. Provide exceptional service "
                "with a warm, professional tone. Anticipate guest needs."
            )
            .with_task_message(
                "Welcome the caller warmly. Ask how you may assist them today."
            )
            .with_function(
                name="handle_booking_request",
                description="Guest wants to make a reservation",
                transition_to="booking"
            )
            .with_function(
                name="handle_inquiry",
                description="Guest has questions about the hotel",
                transition_to="inquiry"
            )
            .with_function(
                name="handle_transfer",
                description="Guest needs to speak with a specific department",
                transition_to="transfer"
            )
            .with_function(
                name="handle_dining",
                description="Guest wants dining recommendations or reservations",
                transition_to="dining"
            )
            .with_function(
                name="handle_activities",
                description="Guest wants activity or tour recommendations",
                transition_to="activities"
            )
            .with_function(
                name="end_call",
                description="End the call",
                transition_to="end"
            )
            .build()
        )
        
        booking = (
            FlowNodeBuilder("booking", "Room Booking")
            .with_task_message(
                "Assist with room reservations. Collect dates, preferences, "
                "and guest information."
            )
            .with_function(
                name="create_booking",
                description="Create the reservation",
                parameters={
                    "type": "object",
                    "properties": {
                        "check_in": {"type": "string"},
                        "check_out": {"type": "string"},
                        "room_type": {"type": "string"},
                        "guest_name": {"type": "string"}
                    },
                    "required": ["check_in", "check_out", "guest_name"]
                },
                transition_to="follow_up"
            )
            .build()
        )
        
        inquiry = (
            FlowNodeBuilder("inquiry", "Guest Inquiry")
            .with_task_message(
                "Answer guest questions using the knowledge base."
            )
            .with_function(
                name="query_hotel_knowledge",
                description="Search knowledge base",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"}
                    },
                    "required": ["question"]
                },
                transition_to="follow_up"
            )
            .build()
        )
        
        transfer = (
            FlowNodeBuilder("transfer", "Call Transfer")
            .with_task_message(
                "Transfer the call to the appropriate department."
            )
            .with_function(
                name="execute_transfer",
                description="Complete the transfer",
                parameters={
                    "type": "object",
                    "properties": {
                        "department": {"type": "string"}
                    },
                    "required": ["department"]
                },
                transition_to="end"
            )
            .build()
        )
        
        dining = (
            FlowNodeBuilder("dining", "Dining Services")
            .with_task_message(
                "Help with restaurant recommendations and reservations."
            )
            .with_function(
                name="make_dining_reservation",
                description="Book a restaurant table",
                parameters={
                    "type": "object",
                    "properties": {
                        "restaurant": {"type": "string"},
                        "date_time": {"type": "string"},
                        "party_size": {"type": "integer"}
                    },
                    "required": ["restaurant", "party_size"]
                },
                transition_to="follow_up"
            )
            .build()
        )
        
        activities = (
            FlowNodeBuilder("activities", "Activities & Tours")
            .with_task_message(
                "Recommend and book local activities, tours, and experiences."
            )
            .with_function(
                name="book_activity",
                description="Book an activity or tour",
                parameters={
                    "type": "object",
                    "properties": {
                        "activity": {"type": "string"},
                        "date": {"type": "string"},
                        "num_guests": {"type": "integer"}
                    },
                    "required": ["activity", "num_guests"]
                },
                transition_to="follow_up"
            )
            .build()
        )
        
        follow_up = (
            FlowNodeBuilder("follow_up", "Follow Up")
            .with_task_message(
                "Ask if there's anything else you can help with."
            )
            .with_function(
                name="continue_assistance",
                description="Guest needs more help",
                transition_to="greeting"
            )
            .with_function(
                name="end_call",
                description="Guest is satisfied",
                transition_to="end"
            )
            .build()
        )
        
        end = (
            FlowNodeBuilder("end", "End Call")
            .with_task_message(
                "Thank the guest and wish them a wonderful stay."
            )
            .as_end_node()
            .build()
        )
        
        return {
            "initial_node": "greeting",
            "nodes": [
                {"id": "greeting", "type": "initial", "data": greeting, "position": {"x": 400, "y": 50}},
                {"id": "booking", "type": "node", "data": booking, "position": {"x": 100, "y": 250}},
                {"id": "inquiry", "type": "node", "data": inquiry, "position": {"x": 250, "y": 250}},
                {"id": "transfer", "type": "node", "data": transfer, "position": {"x": 400, "y": 250}},
                {"id": "dining", "type": "node", "data": dining, "position": {"x": 550, "y": 250}},
                {"id": "activities", "type": "node", "data": activities, "position": {"x": 700, "y": 250}},
                {"id": "follow_up", "type": "node", "data": follow_up, "position": {"x": 400, "y": 450}},
                {"id": "end", "type": "end", "data": end, "position": {"x": 400, "y": 650}}
            ],
            "edges": [
                {"id": "e1", "source": "greeting", "target": "booking"},
                {"id": "e2", "source": "greeting", "target": "inquiry"},
                {"id": "e3", "source": "greeting", "target": "transfer"},
                {"id": "e4", "source": "greeting", "target": "dining"},
                {"id": "e5", "source": "greeting", "target": "activities"},
                {"id": "e6", "source": "booking", "target": "follow_up"},
                {"id": "e7", "source": "inquiry", "target": "follow_up"},
                {"id": "e8", "source": "transfer", "target": "end"},
                {"id": "e9", "source": "dining", "target": "follow_up"},
                {"id": "e10", "source": "activities", "target": "follow_up"},
                {"id": "e11", "source": "follow_up", "target": "greeting"},
                {"id": "e12", "source": "follow_up", "target": "end"},
                {"id": "e13", "source": "greeting", "target": "end"}
            ]
        }
