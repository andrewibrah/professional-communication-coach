export type Scenario={id:string;title:string;description:string;question:string};
export type Config={supabase_url:string;supabase_publishable_key:string;auth_configured:boolean;ai_enabled:boolean;min_recording_seconds:number;max_recording_seconds:number;max_upload_bytes:number;guided_voice_available?:boolean;guided_max_seconds?:number;guided_unavailable_reason?:string};
export type Report={overall_score:number;category_scores:Record<string,number>;communication_strengths:string[];transcript_evidence:{quote:string;observation:string}[];filler_words:{word:string;count:number}[];jargon_flags:string[];pacing_observations:string[];weak_phrasing:string[];missed_questions:string[];priority_improvement:string;suggested_practice_exercise:string;improved_answer:string;next_time_recommendation:string};
export type Attempt={id:string;session_id:string;transcript:string;duration_seconds:number;created_at:string;report:Report};
export type PracticeSession={id:string;scenario_id:string;goal:string;context:string;question:string;example_response:string;created_at:string;attempt_count?:number;latest_score?:number|null;attempts?:Attempt[]};
export type Profile=Record<'role'|'industry'|'experience_level'|'goal'|'tone'|'weakness'|'audience'|'role_description',string>;
export const emptyProfile:Profile={role:'',industry:'',experience_level:'',goal:'',tone:'',weakness:'',audience:'',role_description:''};
export const offlineScenarios:Scenario[]=[
{id:'introduction',title:'Tell me about yourself',description:'Turn your experience into a focused, memorable introduction.',question:'How would you introduce yourself to a prospective employer?'},
{id:'technical-interview',title:'Technical job interview',description:'Explain your approach, not just your technical knowledge.',question:'Walk me through a difficult technical problem you solved.'},
{id:'help-desk',title:'Help-desk troubleshooting',description:'Guide someone from frustration to a practical next step.',question:'How would you help a customer who cannot connect to the internet?'},
{id:'cybersecurity',title:'Explain cybersecurity',description:'Make a complex security topic clear to a nontechnical audience.',question:'Explain why multifactor authentication matters.'},
{id:'sales',title:'Sales discovery & objections',description:'Listen closely, uncover needs, and respond with relevance.',question:'How would you respond to a customer who says the price is too high?'},
{id:'escalation',title:'Customer escalation',description:'Acknowledge the concern and create a credible path forward.',question:'How would you respond to a customer whose issue remains unresolved?'}];
