import React, { useEffect, useState } from "react";

import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Marker
} from "react-leaflet";

import "leaflet/dist/leaflet.css";
import { cities } from "../data/indianCities";
import { getCurrentAQI } from "../services/backendApi";
function AQIHeatmap({ lat, lon, aqi }) {

const [stations, setStations] = useState([]);

const [loading, setLoading] = useState(false);



const getColor = (aqi) => {

if(aqi<=50) return "#22c55e";

if(aqi<=100) return "#eab308";

if(aqi<=150) return "#f97316";

if(aqi<=200) return "#ef4444";

if(aqi<=300) return "#9333ea";

return "#7f1d1d";

};



const getStatus = (aqi) => {

if(aqi<=50)

return "Good";

if(aqi<=100)

return "Moderate";

if(aqi<=150)

return "Unhealthy for Sensitive Groups";

if(aqi<=200)

return "Unhealthy";

if(aqi<=300)

return "Very Unhealthy";

return "Hazardous";

};





const getRadius=(aqi)=>{

if(aqi<=50)

return 10;

if(aqi<=100)

return 14;

if(aqi<=150)

return 18;

if(aqi<=200)

return 22;

return 26;

};





const fetchAQI=async()=>{
    try{
        setLoading(true);
        const results=[];
        for(const city of cities){
            try{
                const data = await getCurrentAQI(city.name);
                if(data && data.status === "ok"){
                    results.push({
                        name:city.name,
                        lat:city.lat,
                        lon:city.lon,
                        aqi:data.data.aqi
                    });
                }
            }
            catch(err){
                console.log(err);
            }
        }
        setStations(results);
    }
    catch(err){
        console.log(err);
    }
    finally{
        setLoading(false);
    }
};





useEffect(()=>{

fetchAQI();


const interval=

setInterval(

fetchAQI,

180000

);


return()=>clearInterval(interval);

},[]);







return(

<div className="card">

<h2>

🌍 Live India AQI Heatmap

</h2>



<p>

Real-time air quality of major Indian cities

</p>



{

loading &&

<p>

Loading AQI...

</p>

}



<MapContainer

center={[20.5937,78.9629]}

zoom={5}

style={{

height:"650px",

width:"100%",

borderRadius:"20px",

marginTop:"20px"

}}

>

<TileLayer

attribution='&copy; OpenStreetMap'

url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

/>





{

stations.map(

(station,index)=>(

<CircleMarker

key={index}

center={[

station.lat,

station.lon

]}

radius={

getRadius(

station.aqi

)

}

fillColor={

getColor(

station.aqi

)

}

fillOpacity={0.85}

color="#ffffff"

weight={2}

>

<Popup>

<h3>

📍

{" "}

{station.name}

</h3>


<p>

AQI :

<b>

{" "}

{station.aqi}

</b>

</p>


<p>

Status :

<b>

{" "}

{

getStatus(

station.aqi

)

}

</b>

</p>

</Popup>

</CircleMarker>

)

)

}





{

lat

&&

lon

&&

<Marker

position={[

lat,

lon

]}

>

<Popup>

📍

<b>

Your Location

</b>


<br/>


AQI :

<b>

{" "}

{aqi}

</b>

</Popup>

</Marker>

}



</MapContainer>







<div

style={{

display:"flex",

justifyContent:"center",

gap:"18px",

flexWrap:"wrap",

marginTop:"20px",

fontWeight:"bold"

}}

>

<div>

🟢 0-50 Good

</div>


<div>

🟡 51-100 Moderate

</div>


<div>

🟠 101-150 USG

</div>


<div>

🔴 151-200 Unhealthy

</div>


<div>

🟣 201-300 Very Unhealthy

</div>


<div>

⚫ 300+ Hazardous

</div>


</div>








<div

style={{

marginTop:"25px",

padding:"20px",

background:"#1e293b",

borderRadius:"18px"

}}

>

<h3>

🏆 Top Polluted Cities

</h3>


<table

style={{

width:"100%",

marginTop:"15px",

textAlign:"left"

}}

>

<thead>

<tr>

<th>

City

</th>

<th>

AQI

</th>

<th>

Status

</th>

</tr>

</thead>


<tbody>

{

[...stations]

.sort(

(a,b)=>

b.aqi-a.aqi

)

.slice(0,5)

.map(

(city,index)=>

<tr key={index}>

<td>

{city.name}

</td>


<td>

{city.aqi}

</td>


<td>

{

getStatus(

city.aqi

)

}

</td>

</tr>

)

}

</tbody>

</table>


</div>



</div>

);

}


export default AQIHeatmap;