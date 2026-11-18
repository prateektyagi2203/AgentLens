export const THEME_KEY = "agentlens-theme";
export const STORY_KEY = "agentlens-story";

/** Runs before first paint (inlined in <head> by app/layout.tsx) so there is no theme flash. */
export const THEME_INIT_SCRIPT = `(function(){try{var d=document.documentElement,t=localStorage.getItem("${THEME_KEY}");if(!t){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}d.dataset.theme=t;if(localStorage.getItem("${STORY_KEY}")==="1")d.dataset.story="on"}catch(e){}})()`;
