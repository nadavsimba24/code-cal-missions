"""
CityOS — Agent Swarm
Multi-agent AI system for municipal workflow management.
Each agent has a specialized role and uses the local Gemma 4 model.
"""

import json, os, subprocess, re
from datetime import datetime, timezone
from typing import Optional

class CityOSAgent:
    """Base agent that communicates with Gemma 4 via Ollama."""
    
    def __init__(self, name: str, role: str, system_prompt: str):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.conversation = []
    
    def think(self, task: str, context: dict = None) -> str:
        """Run the agent's reasoning on a task."""
        ctx = json.dumps(context, ensure_ascii=False) if context else "{}"
        prompt = f"""{self.system_prompt}

Context: {ctx}

Task: {task}

Respond in Hebrew. Be concise and actionable."""
        
        try:
            result = subprocess.run(
                ["ollama", "run", "gemma4-coder", prompt],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "OLLAMA_NUM_THREADS": "4"}  # Gentle on resources
            )
            response = result.stdout.strip()
            # Extract just the answer (after chain-of-thought)
            lines = response.split('\n')
            clean_lines = [l for l in lines if l.strip() and not l.strip().startswith(('Goal:', 'Edge', 'Plan:', '...'))]
            response = '\n'.join(clean_lines) if clean_lines else response
            
            self.conversation.append({"role": "assistant", "content": response})
            return response
        except Exception as e:
            return f"⚠️ {self.name} לא זמין: {str(e)}"


class AgentSwarm:
    """
    CityOS Agent Swarm — specialized agents collaborating on municipal tasks.
    
    Agents:
      🏗️ Builder Agent     — Project planning & task breakdown
      🚌 Transport Agent   — SIRI data analysis & route optimization
      📋 Form Agent        — Smart form generation & validation
      📊 Insight Agent     — Board analytics & pattern detection
      🎨 Viz Agent         — Data visualization recommendations
      🔮 Predict Agent     — Timeline forecasting & risk detection
    """
    
    def __init__(self):
        self.agents = {
            "builder": CityOSAgent(
                "Builder", "🏗️ תכנון פרויקטים",
                "You are a municipal infrastructure project planner. Break down complex projects into "
                "manageable tasks, identify dependencies, estimate timelines, and flag risks."
            ),
            "transport": CityOSAgent(
                "Transport", "🚌 תחבורה ציבורית",
                "You are a public transport analyst specializing in SIRI real-time data. Analyze stop "
                "monitoring data, suggest route optimizations, and identify service gaps."
            ),
            "forms": CityOSAgent(
                "Forms", "📋 יצירת טפסים חכמים",
                "You are a form design expert for municipal services. Generate smart form structures "
                "for building permits, citizen requests, and municipal workflows."
            ),
            "insights": CityOSAgent(
                "Insights", "📊 ניתוח נתונים עירוניים",
                "You are a municipal data analyst. Extract insights from board data, identify bottlenecks, "
                "detect patterns in task completion, and suggest process improvements."
            ),
            "viz": CityOSAgent(
                "VizArtist", "🎨 ויזואליזציה",
                "You are a data visualization expert. Recommend chart types, generate visualization "
                "configurations, and describe data stories from board data."
            ),
            "predict": CityOSAgent(
                "Predictor", "🔮 חיזוי ותזמון",
                "You are a municipal timeline forecaster. Predict project delays, identify risk patterns, "
                "optimize resource allocation, and suggest preventive measures."
            ),
        }
    
    def get_agent(self, name: str) -> Optional[CityOSAgent]:
        return self.agents.get(name)
    
    def swarm_think(self, task: str, context: dict = None) -> dict:
        """Run all agents on a task and collect responses."""
        results = {}
        for name, agent in self.agents.items():
            results[name] = agent.think(task, context)
        return results
    
    def coordinated_think(self, task: str, context: dict = None) -> dict:
        """
        Run agents in sequence, passing context between them.
        1. Builder plans      2. Predict assesses risks
        3. Insights analyzes  4. Viz recommends visuals
        5. Forms generates    6. Transport checks logistics
        """
        results = {}
        order = ["builder", "predict", "insights", "viz", "forms", "transport"]
        
        for name in order:
            agent = self.agents[name]
            # Include previous agents' outputs as context
            enriched_context = {
                **(context or {}),
                "previous_insights": results,
            }
            results[name] = agent.think(task, enriched_context)
        
        return results

# Singleton
_swarm = None

def get_swarm() -> AgentSwarm:
    global _swarm
    if _swarm is None:
        _swarm = AgentSwarm()
    return _swarm

def swarm_api(agent: str = "", task: str = "", context: dict = None, mode: str = "single"):
    """API interface for the agent swarm."""
    swarm = get_swarm()
    
    if mode == "all":
        return swarm.swarm_think(task, context)
    elif mode == "coordinated":
        return swarm.coordinated_think(task, context)
    elif agent:
        a = swarm.get_agent(agent)
        if a:
            return {agent: a.think(task, context)}
        return {"error": f"Agent '{agent}' not found. Available: {list(swarm.agents.keys())}"}
    else:
        return {"error": "Specify agent or mode"}
