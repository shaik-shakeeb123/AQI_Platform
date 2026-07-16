import React from "react";

function Settings({

theme,

setTheme

}) {

return (

<div className="card">

<h2>

⚙ Settings

</h2>

<br/>

<h3>

Theme

</h3>

<br/>

<button

onClick={()=>

setTheme("light")

}

>

☀ Light

</button>

{" "}

<button

onClick={()=>

setTheme("dark")

}

>

🌙 Dark

</button>

<br/>

<br/>

<h3>

Notifications

</h3>

<br/>

<label>

<input

type="checkbox"

defaultChecked

/>

 Enable AQI Alerts

</label>

<br/>

<br/>

<label>

<input

type="checkbox"

defaultChecked

/>

 Enable Weather Alerts

</label>

</div>

);

}

export default Settings;