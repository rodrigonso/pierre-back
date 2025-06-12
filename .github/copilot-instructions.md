# COPILOT EDITS OPERATIONAL GUIDELINES

## PRIME DIRECTIVE
	- Avoid working on more than one file at a time.
	- Multiple simultaneous edits to a file will cause corruption.
	- Be chatting and teach about what you are doing while coding.

## LARGE FILE & COMPLEX CHANGE PROTOCOL

### MANDATORY PLANNING PHASE
	When working with large files (>300 lines) or complex changes:
		1. ALWAYS start by creating a detailed plan BEFORE making any edits
            2. Your plan MUST include:
                   - All functions/sections that need modification
                   - The order in which changes should be applied
                   - Dependencies between changes
                   - Estimated number of separate edits required
                
            3. Format your plan as:
## PROPOSED EDIT PLAN
	Working with: [filename]
	Total planned edits: [number]

### MAKING EDITS
	- Focus on one conceptual change at a time
	- Show clear "before" and "after" snippets when proposing changes
	- Include concise explanations of what changed and why
	- Always check if the edit maintains the project's coding style

### Edit sequence:
	1. [First specific change] - Purpose: [why]
	2. [Second specific change] - Purpose: [why]
	3. Do you approve this plan? I'll proceed with Edit [number] after your confirmation.
	4. WAIT for explicit user confirmation before making ANY edits when user ok edit [number]
            
### EXECUTION PHASE
	- After each individual edit, clearly indicate progress:
		"✅ Completed edit [#] of [total]. Ready for next edit?"
	- If you discover additional needed changes during editing:
	- STOP and update the plan
	- Get approval before continuing
                
### REFACTORING GUIDANCE
	When refactoring large files:
	- Break work into logical, independently functional chunks
	- Ensure each intermediate state maintains functionality
	- Consider temporary duplication as a valid interim step
	- Always indicate the refactoring pattern being applied
                
### RATE LIMIT AVOIDANCE
	- For very large files, suggest splitting changes across multiple sessions
	- Prioritize changes that are logically complete units
	- Always provide clear stopping points
            
## General Requirements
	- Use modern technologies as described below for all code suggestions. Prioritize clean, maintainable code with appropriate comments.
                        
## Python Requirements
	- Make sure you are favoring using Pydantic objects instead of vanilla dictionary as much as possible (and where it makes sense)
	- Don't get stuck trying to fix indentation issues. I can solve these myself. Focus on implementing quality code based on the request.
	- When installing packages makes sure that you active the virtual environment first.
	- Use `pip` for package management.

## Documentation Requirements
	- Include documentation for python
	- Document complex functions with clear examples.
	- Maintain concise Markdown documentation.
	- Minimum docblock info: `param`, `return`, `throws`
    
## Database Requirements (Supabase)
	- Ensure that all database tables have proper RLS and policies set up.
	- Use Supabase's Postgres features effectively.
	- Write proper SQL migrations for schema changes.
	- Use Supabase's built-in authentication and authorization features.
	- Use Supabase's real-time capabilities where applicable.

## API Requirements
	- Use FastAPI for building APIs.
	- Ensure all endpoints are properly documented with OpenAPI.
	- Implement proper error handling and response formatting.
	- Use Pydantic models for request and response validation.
	- Implement rate limiting where necessary.
	- Use CORS middleware to allow cross-origin requests where needed.
	- Implement authentication and authorization using Supabase Auth.
    
## Security Considerations
	- Sanitize all user inputs thoroughly.
	- Parameterize database queries.
	- Enforce strong Content Security Policies (CSP).
	- Use CSRF protection where applicable.
	- Ensure secure cookies (`HttpOnly`, `Secure`, `SameSite=Strict`).
	- Limit privileges and enforce role-based access control.
	- Implement detailed internal logging and monitoring.

## Environment Configuration
	- Use `.env` files for environment-specific configurations.
	- Ensure sensitive information is not hard-coded.
	- Use environment variables for configuration management.