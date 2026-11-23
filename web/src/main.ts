import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

async function start() {
  if (import.meta.env.MODE === 'demo') (await import('./lib/demo')).install()
  mount(App, { target: document.getElementById('app')! })
}

start()
