// A request belongs to an operation, not to the DOM node that happened to start it.
// Read responses also belong to a view revision, so older pages cannot overwrite
// a newer search. Mutations are never automatically retried or cancelled here.
export class Requests {
  constructor(changed=()=>{}) {this.pending=new Map();this.revision=0;this.changed=changed;}
  nextView() {return ++this.revision;}
  current(revision) {return revision===this.revision;}
  busy(key) {return key===undefined?this.pending.size>0:this.pending.has(key);}
  run(key,operation) {
    if(this.pending.has(key))return this.pending.get(key);
    const promise=Promise.resolve().then(operation).finally(()=>{
      this.pending.delete(key);this.changed();
    });
    this.pending.set(key,promise);this.changed();return promise;
  }
}
