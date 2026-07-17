import React from "react";
import "./WeatherBackground.css";

function WeatherBackground({ weather = "Clear" }) {

const type = weather.toLowerCase();

let effect = "sunny";

if (type.includes("rain")) {

effect = "rain";

}

else if (type.includes("cloud")) {

effect = "cloudy";

}

else if (

type.includes("mist") ||

type.includes("fog")

) {

effect = "fog";

}

else if (

type.includes("night")

) {

effect = "night";

}

return (

<div className={`weather-bg ${effect}`}>

{

effect==="sunny"

&&

<div className="sun"></div>

}



{

effect==="cloudy"

&&

<>

<div className="cloud cloud1"></div>

<div className="cloud cloud2"></div>

<div className="cloud cloud3"></div>

</>

}



{

effect==="rain"

&&

<div className="rain-container">

{

Array.from({ length: 70 }).map((_,i)=>(

<div

key={i}

className="raindrop"

style={{

left:`${Math.random()*100}%`,

animationDelay:`${Math.random()*2}s`

}}

>

</div>

))

}

</div>

}



{

effect==="fog"

&&

<div className="fog"></div>

}



{

effect==="night"

&&

<>

<div className="moon"></div>

{

Array.from({ length:40 }).map((_,i)=>(

<div

key={i}

className="star"

style={{

left:`${Math.random()*100}%`,

top:`${Math.random()*100}%`

}}

>

</div>

))

}

</>

}

</div>

);

}

export default WeatherBackground;